#!/usr/bin/python

DOCUMENTATION = '''
---
module: redhat_subscription
short_description: Manage Red Hat Network registration and subscriptions using the C(subscription-manager) command
description:
    - Manage registration and subscription to the Red Hat Network entitlement platform.
version_added: "1.2"
author: James Laska
notes:
    - In order to register a system, subscription-manager requires either a username and password, or an activationkey.
requirements:
    - subscription-manager
options:
    state:
        description:
          - whether to register and subscribe (C(present)), or unregister (C(absent)) a system
        required: false
        choices: [ "present", "absent" ]
        default: "present"
    username:
        description:
            - Red Hat Network username
        required: False
        default: null
    password:
        description:
            - Red Hat Network password
        required: False
        default: null
    server_hostname:
        description:
            - Specify an alternative Red Hat Network server
        required: False
        default: Current value from C(/etc/rhsm/rhsm.conf) is the default
    server_insecure:
        description:
            - Allow traffic over insecure http
        required: False
        default: Current value from C(/etc/rhsm/rhsm.conf) is the default
    rhsm_baseurl:
        description:
            - Specify CDN baseurl
        required: False
        default: Current value from C(/etc/rhsm/rhsm.conf) is the default
    autosubscribe:
        description:
            - Upon successful registration, auto-consume available subscriptions
        required: False
        default: False
    activationkey:
        description:
            - supply an activation key for use with registration
        required: False
        default: null
    pool:
        description:
            - Specify a subscription pool name to consume.  Regular expressions accepted.
        required: False
        default: '^$'
'''

EXAMPLES = '''
# Register as user (joe_user) with password (somepass) and auto-subscribe to available content.
- redhat_subscription: action=register username=joe_user password=somepass autosubscribe=true

# Register with activationkey (1-222333444) and consume subscriptions matching
# the names (Red hat Enterprise Server) and (Red Hat Virtualization)
- redhat_subscription: action=register
                       activationkey=1-222333444
                       pool='^(Red Hat Enterprise Server|Red Hat Virtualization)$'
'''

import os
import re
import types
import subprocess
import ConfigParser
import shlex


class CommandException(Exception):
    pass


def run_command(args):
    '''
        Convenience method to run a command, specified as a list of arguments.
        Returns:
            * tuple - (stdout, stder, retcode)
    '''

    # Coerce into a string
    if isinstance(args, str):
        args = shlex.split(args)

    # Run desired command
    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)
    (stdout, stderr) = proc.communicate()
    returncode = proc.poll()
    if returncode != 0:
        cmd = ' '.join(args)
        raise CommandException("Command failed (%s): %s\n%s" % (returncode, cmd, stdout))
    return (stdout, stderr, returncode)


class RegistrationBase (object):
    def __init__(self, username=None, password=None):
        self.username = username
        self.password = password

    def configure(self):
        raise NotImplementedError("Must be implemented by a sub-class")

    def enable(self):
        # Remove any existing redhat.repo
        redhat_repo = '/etc/yum.repos.d/redhat.repo'
        if os.path.isfile(redhat_repo):
            os.unlink(redhat_repo)

    def register(self):
        raise NotImplementedError("Must be implemented by a sub-class")

    def unregister(self):
        raise NotImplementedError("Must be implemented by a sub-class")

    def unsubscribe(self):
        raise NotImplementedError("Must be implemented by a sub-class")

    def update_plugin_conf(self, plugin, enabled=True):
        plugin_conf = '/etc/yum/pluginconf.d/%s.conf' % plugin
        if os.path.isfile(plugin_conf):
            cfg = ConfigParser.ConfigParser()
            cfg.read([plugin_conf])
            if enabled:
                cfg.set('main', 'enabled', 1)
            else:
                cfg.set('main', 'enabled', 0)
            fd = open(plugin_conf, 'rwa+')
            cfg.write(fd)
            fd.close()

    def subscribe(self, **kwargs):
        raise NotImplementedError("Must be implemented by a sub-class")


class Rhsm(RegistrationBase):
    def __init__(self, username=None, password=None):
        RegistrationBase.__init__(self, username, password)
        self.config = self._read_config()

    def _read_config(self, rhsm_conf='/etc/rhsm/rhsm.conf'):
        '''
            Load RHSM configuration from /etc/rhsm/rhsm.conf.
            Returns:
             * ConfigParser object
        '''

        # Read RHSM defaults ...
        cp = ConfigParser.ConfigParser()
        cp.read(rhsm_conf)

        # Add support for specifying a default value w/o having to standup some configuration
        # Yeah, I know this should be subclassed ... but, oh well
        def get_option_default(self, key, default=''):
            sect, opt = key.split('.', 1)
            if self.has_section(sect) and self.has_option(sect, opt):
                return self.get(sect, opt)
            else:
                return default

        cp.get_option = types.MethodType(get_option_default, cp, ConfigParser.ConfigParser)

        return cp

    def enable(self):
        '''
            Enable the system to receive updates from subscription-manager.
            This involves updating affected yum plugins and removing any
            conflicting yum repositories.
        '''
        RegistrationBase.enable(self)
        self.update_plugin_conf('rhnplugin', False)
        self.update_plugin_conf('subscription-manager', True)

    def configure(self, **kwargs):
        '''
            Configure the system as directed for registration with RHN
            Raises:
              * Exception - if error occurs while running command
        '''
        args = ['subscription-manager', 'config']

        # Pass supplied **kwargs as parameters to subscription-manager.  Ignore
        # non-configuration parameters and replace '_' with '.'.  For example,
        # 'server_hostname' becomes '--system.hostname'.
        for k,v in kwargs.items():
            if re.search(r'^(system|rhsm)_', k):
                args.append('--%s=%s' % (k.replace('_','.'), v))

        run_command(args)

    @property
    def is_registered(self):
        '''
            Determine whether the current system
            Returns:
              * Boolean - whether the current system is currently registered to
                          RHN.
        '''
        # Quick version...
        if False:
            return os.path.isfile('/etc/pki/consumer/cert.pem') and \
                   os.path.isfile('/etc/pki/consumer/key.pem')

        args = ['subscription-manager', 'identity']
        try:
            (stdout, stderr, retcode) = run_command(args)
        except CommandException, e:
            return False
        else:
            # Display some debug output
            return True

    def register(self, username, password, autosubscribe, activationkey):
        '''
            Register the current system to the provided RHN server
            Raises:
              * Exception - if error occurs while running command
        '''
        args = ['subscription-manager', 'register']

        # Generate command arguments
        if activationkey:
            args.append('--activationkey "%s"' % activationkey)
        else:
            if autosubscribe:
                args.append('--autosubscribe')
            if username:
                args.extend(['--username', username])
            if password:
                args.extend(['--password', password])

        # Do the needful...
        run_command(args)

    def unsubscribe(self):
        '''
            Unsubscribe a system from all subscribed channels
            Raises:
              * Exception - if error occurs while running command
        '''
        args = ['subscription-manager', 'unsubscribe', '--all']
        run_command(args)

    def unregister(self):
        '''
            Unregister a currently registered system
            Raises:
              * Exception - if error occurs while running command
        '''
        args = ['subscription-manager', 'unregister']
        run_command(args)

    def subscribe(self, regexp):
        '''
            Subscribe current system to available pools matching the specified
            regular expression
            Raises:
              * Exception - if error occurs while running command
        '''

        # Available pools ready for subscription
        available_pools = RhsmPools()

        for pool in available_pools.filter(regexp):
            pool.subscribe()


class RhsmPool(object):
    '''
        Convenience class for housing subscription information
    '''

    def __init__(self, **kwargs):
        for k,v in kwargs.items():
            setattr(self, k, v)

    def __str__(self):
        return str(self.__getattribute__('_name'))

    def subscribe(self):
        (stdout, stderr, retcode) = run_command("subscription-manager subscribe --pool %s" % self.PoolId)
        return True


class RhsmPools(object):
    """
        This class is used for manipulating pools subscriptions with RHSM
    """
    def __init__(self):
        self.products = self._load_product_list()

    def __iter__(self):
        return self.products.__iter__()

    def _load_product_list(self):
        """
            Loads list of all availaible pools for system in data structure
        """
        (stdout, stderr, retval) = run_command("subscription-manager list --available")

        products = []
        for line in stdout.split('\n'):
            # Remove leading+trailing whitespace
            line = line.strip()
            # An empty line implies the end of a output group
            if len(line) == 0:
                continue
            # If a colon ':' is found, parse
            elif ':' in line:
                (key, value) = line.split(':',1)
                key = key.strip().replace(" ", "")  # To unify
                value = value.strip()
                if key in ['ProductName', 'SubscriptionName']:
                    # Remember the name for later processing
                    products.append(RhsmPool(_name=value, key=value))
                elif products:
                    # Associate value with most recently recorded product
                    products[-1].__setattr__(key, value)
                # FIXME - log some warning?
                #else:
                    # warnings.warn("Unhandled subscription key/value: %s/%s" % (key,value))
        return products

    def filter(self, regexp='^$'):
        '''
            Return a list of RhsmPools whose name matches the provided regular expression
        '''
        r = re.compile(regexp)
        for product in self.products:
            if r.search(product._name):
                yield product


def main():

    # Load RHSM configuration from file
    rhn = Rhsm()

    module = AnsibleModule(
                argument_spec = dict(
                    state = dict(default='present', choices=['present', 'absent']),
                    username = dict(default=None, required=False),
                    password = dict(default=None, required=False),
                    server_hostname = dict(default=rhn.config.get_option('server.hostname'), required=False),
                    server_insecure = dict(default=rhn.config.get_option('server.insecure'), required=False),
                    rhsm_baseurl = dict(default=rhn.config.get_option('rhsm.baseurl'), required=False),
                    autosubscribe = dict(default=False, type='bool'),
                    activationkey = dict(default=None, required=False),
                    pool = dict(default='^$', required=False, type='str'),
                )
            )

    state = module.params['state']
    username = module.params['username']
    password = module.params['password']
    server_hostname = module.params['server_hostname']
    server_insecure = module.params['server_insecure']
    rhsm_baseurl = module.params['rhsm_baseurl']
    autosubscribe = module.params['autosubscribe'] == True
    activationkey = module.params['activationkey']
    pool = module.params['pool']

    # Ensure system is registered
    if state == 'present':

        # Check for missing parameters ...
        if not (activationkey or username or password):
            module.fail_json(msg="Missing arguments, must supply an activationkey (%s) or username (%s) and password (%s)" % (activationkey, username, password))
        if not activationkey and not (username and password):
            module.fail_json(msg="Missing arguments, If registering without an activationkey, must supply username or password")

        # Register system
        if rhn.is_registered:
            module.exit_json(changed=False, msg="System already registered.")
        else:
            try:
                rhn.enable()
                rhn.configure(**module.params)
                rhn.register(username, password, autosubscribe, activationkey)
                rhn.subscribe(pool)
            except CommandException, e:
                module.fail_json(msg="Failed to register with '%s': %s" % (server_hostname, e))
            else:
                module.exit_json(changed=True, msg="System successfully registered to '%s'." % server_hostname)

    # Ensure system is *not* registered
    if state == 'absent':
        if not rhn.is_registered:
            module.exit_json(changed=False, msg="System already unregistered.")
        else:
            try:
                rhn.unsubscribe()
                rhn.unregister()
            except CommandException, e:
                module.fail_json(msg="Failed to unregister: %s" % e)
            else:
                module.exit_json(changed=True, msg="System successfully unregistered from %s." % server_hostname)


# include magic from lib/ansible/module_common.py
#<<INCLUDE_ANSIBLE_MODULE_COMMON>>
main()
