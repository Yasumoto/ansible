#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2013, Hiroaki Nakamura <hnakamur@gmail.com>
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

DOCUMENTATION = '''
---
module: hostname
author: Hiroaki Nakamura
version_added: "1.4"
short_description: Manage hostname
requirements: [ hostname ]
description:
    - Set system's hostname
    - Currently implemented on only Debian, Ubuntu, RedHat and CentOS.
options:
    name:
        required: true
        description:
            - Name of the host
'''

EXAMPLES = '''
- hostname: name=web01
'''

class UnimplementedStrategy(object):
    def __init__(self, module):
        self.module = module

    def get_current_hostname(self):
        self.unimplemented_error()

    def set_current_hostname(self, name):
        self.unimplemented_error()

    def get_permanent_hostname(self):
        self.unimplemented_error()

    def set_permanent_hostname(self, name):
        self.unimplemented_error()

    def unimplemented_error(self):
        platform = get_platform()
        distribution = get_distribution()
        if distribution is not None:
            msg_platform = '%s (%s)' % (platform, distribution)
        else:
            msg_platform = platform
        self.module.fail_json(
            msg='hostname module cannot be used on platform %s' % msg_platform)

class Hostname(object):
    """
    This is a generic Hostname manipulation class that is subclassed
    based on platform.

    A subclass may wish to set different strategy instance to self.strategy.

    All subclasses MUST define platform and distribution (which may be None).
    """

    platform = 'Generic'
    distribution = None
    strategy_class = UnimplementedStrategy

    def __new__(cls, *args, **kwargs):
        return load_platform_subclass(Hostname, args, kwargs)

    def __init__(self, module):
        self.module   = module
        self.name     = module.params['name']
        self.strategy = self.strategy_class(module)

    def get_current_hostname(self):
        return self.strategy.get_current_hostname()

    def set_current_hostname(self, name):
        self.strategy.set_current_hostname(name)

    def get_permanent_hostname(self):
        return self.strategy.get_permanent_hostname()

    def set_permanent_hostname(self, name):
        self.strategy.set_permanent_hostname(name)

class GenericStrategy(object):
    """
    This is a generic Hostname manipulation strategy class.

    A subclass may wish to override some or all of these methods.
      - get_current_hostname()
      - get_permanent_hostname()
      - set_current_hostname(name)
      - set_permanent_hostname(name)
    """
    def __init__(self, module):
        self.module = module

    HOSTNAME_CMD = '/bin/hostname'

    def get_current_hostname(self):
        cmd = [self.HOSTNAME_CMD]
        rc, out, err = self.module.run_command(cmd)
        if rc != 0:
            self.module.fail_json(msg="Command failed rc=%d, out=%s, err=%s" %
                (rc, out, err))
        return out.strip()

    def set_current_hostname(self, name):
        cmd = [self.HOSTNAME_CMD, name]
        rc, out, err = self.module.run_command(cmd)
        if rc != 0:
            self.module.fail_json(msg="Command failed rc=%d, out=%s, err=%s" %
                (rc, out, err))

    def get_permanent_hostname(self):
        return None

    def set_permanent_hostname(self, name):
        pass

# ===========================================

class DebianStrategy(GenericStrategy):
    """
    This is a Debian family Hostname manipulation strategy class - it edits
    the /etc/hostname file.
    """

    HOSTNAME_FILE = '/etc/hostname'

    def get_permanent_hostname(self):
        try:
            f = open(self.HOSTNAME_FILE)
            try:
                return f.read().strip()
            finally:
                f.close()
        except Exception, err:
            self.module.fail_json(msg="failed to read hostname: %s" %
                str(err))

    def set_permanent_hostname(self, name):
        try:
            f = open(self.HOSTNAME_FILE, 'w+')
            try:
                f.write("%s\n" % name)
            finally:
                f.close()
        except Exception, err:
            self.module.fail_json(msg="failed to update hostname: %s" %
                str(err))

class DebianHostname(Hostname):
    platform = 'Linux'
    distribution = 'Debian'
    strategy_class = DebianStrategy

class UbuntuHostname(Hostname):
    platform = 'Linux'
    distribution = 'Ubuntu'
    strategy_class = DebianStrategy

# ===========================================

class RedHatStrategy(GenericStrategy):
    """
    This is a Redhat Hostname strategy class - it edits the
    /etc/sysconfig/network file.
    """
    NETWORK_FILE = '/etc/sysconfig/network'

    def get_permanent_hostname(self):
        try:
            f = open(self.NETWORK_FILE, 'rb')
            try:
                for line in f.readlines():
                    if line.startswith('HOSTNAME'):
                        k, v = line.split('=')
                        return v.strip()
            finally:
                f.close()
        except Exception, err:
            self.module.fail_json(msg="failed to read hostname: %s" %
                str(err))

    def set_permanent_hostname(self, name):
        try:
            lines = []
            f = open(self.NETWORK_FILE, 'rb')
            try:
                for line in f.readlines():
                    if line.startswith('HOSTNAME'):
                        lines.append("HOSTNAME=%s\n" % name)
                    else:
                        lines.append(line)
            finally:
                f.close()
            f = open(self.NETWORK_FILE, 'w+')
            try:
                f.writelines(lines)
            finally:
                f.close()
        except Exception, err:
            self.module.fail_json(msg="failed to update hostname: %s" %
                str(err))

class RedHatHostname(Hostname):
    platform = 'Linux'
    distribution = 'Red hat enterprise linux server'
    strategy_class = RedHatStrategy

class CentOSHostname(Hostname):
    platform = 'Linux'
    distribution = 'Centos'
    strategy_class = RedHatStrategy

# ===========================================

class FedoraStrategy(GenericStrategy):
    """
    This is a Fedora family Hostname manipulation strategy class - it uses
    the hostnamectl command.
    """

    def get_current_hostname(self):
        cmd = ['hostname']
        rc, out, err = self.module.run_command(cmd)
        if rc != 0:
            self.module.fail_json(msg="Command failed rc=%d, out=%s, err=%s" %
                (rc, out, err))
        return out.strip()

    def set_current_hostname(self, name):
        cmd = ['hostnamectl', '--transient', 'set-hostname', name]
        rc, out, err = self.module.run_command(cmd)
        if rc != 0:
            self.module.fail_json(msg="Command failed rc=%d, out=%s, err=%s" %
                (rc, out, err))

    def get_permanent_hostname(self):
        cmd = 'hostnamectl status | awk \'/^ *Static hostname:/{printf("%s", $3)}\''
        rc, out, err = self.module.run_command(cmd)
        if rc != 0:
            self.module.fail_json(msg="Command failed rc=%d, out=%s, err=%s" %
                (rc, out, err))
	return out

    def set_permanent_hostname(self, name):
        cmd = ['hostnamectl', '--pretty', 'set-hostname', name]
        rc, out, err = self.module.run_command(cmd)
        if rc != 0:
            self.module.fail_json(msg="Command failed rc=%d, out=%s, err=%s" %
                (rc, out, err))
        cmd = ['hostnamectl', '--static', 'set-hostname', name]
        rc, out, err = self.module.run_command(cmd)
        if rc != 0:
            self.module.fail_json(msg="Command failed rc=%d, out=%s, err=%s" %
                (rc, out, err))

class FedoraHostname(Hostname):
    platform = 'Linux'
    distribution = 'Fedora'
    strategy_class = FedoraStrategy

class OpenSUSEHostname(Hostname):
    platform = 'Linux'
    distribution = 'Opensuse '
    strategy_class = FedoraStrategy

class ArchHostname(Hostname):
    platform = 'Linux'
    distribution = 'Arch'
    strategy_class = FedoraStrategy

# ===========================================

def main():
    module = AnsibleModule(
        argument_spec = dict(
            name=dict(required=True, type='str')
        )
    )

    hostname = Hostname(module)

    changed = False
    name = module.params['name']
    current_name = hostname.get_current_hostname()
    if current_name != name:
        hostname.set_current_hostname(name)
        changed = True

    permanent_name = hostname.get_permanent_hostname()
    if permanent_name != name:
        hostname.set_permanent_hostname(name)
        changed = True

    module.exit_json(changed=changed, name=name)

# include magic from lib/ansible/module_common.py
#<<INCLUDE_ANSIBLE_MODULE_COMMON>>
main()
