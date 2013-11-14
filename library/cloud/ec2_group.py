#!/usr/bin/python
# -*- coding: utf-8 -*-


DOCUMENTATION = '''
---
module: ec2_group
short_description: maintain an ec2 VPC security group.
description:
    - maintains ec2 security groups. This module has a dependency on python-boto >= 2.5
options:
  name:
    description:
      - Name of the security group.
    required: true
  description:
    description:
      - Description of the security group.
    required: true
  vpc_id:
    description:
      - ID of the VPC to create the group in.
    required: false
  rules:
    description:
      - List of firewall rules to enforce in this group (see example).
    required: true
  region:
    description:
      - the EC2 region to use
    required: false
    default: null
    aliases: []
  ec2_url:
    description:
      - Url to use to connect to EC2 or your Eucalyptus cloud (by default the module will use EC2 endpoints)
    required: false
    default: null
    aliases: []
  ec2_secret_key:
    description:
      - EC2 secret key
    required: false
    default: null
    aliases: ['aws_secret_key']
  ec2_access_key:
    description:
      - EC2 access key
    required: false
    default: null
    aliases: ['aws_access_key']
  state:
    version_added: "1.4"
    description:
      - create or delete security group
    required: false
    default: 'present'
    aliases: []

requirements: [ "boto" ]
'''

EXAMPLES = '''
- name: example ec2 group
  local_action:
    module: ec2_group
    name: example
    description: an example EC2 group
    vpc_id: 12345
    region: eu-west-1a
    ec2_secret_key: SECRET
    ec2_access_key: ACCESS
    rules:
      - proto: tcp
        from_port: 80
        to_port: 80
        cidr_ip: 0.0.0.0/0
      - proto: tcp
        from_port: 22
        to_port: 22
        cidr_ip: 10.0.0.0/8
      - proto: udp
        from_port: 10050
        to_port: 10050
        cidr_ip: 10.0.0.0/8
      - proto: udp
        from_port: 10051
        to_port: 10051
        group_id: abcdef
'''

try:
    import boto.ec2
except ImportError:
    print "failed=True msg='boto required for this module'"
    sys.exit(1)


def addRulesToLookup(rules, prefix, dict):
    for rule in rules:
        for grant in rule.grants:
            dict["%s-%s-%s-%s-%s-%s" % (prefix, rule.ip_protocol, rule.from_port, rule.to_port,
                                        grant.group_id, grant.cidr_ip)] = rule

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(required=True),
            description=dict(required=True),
            vpc_id=dict(),
            rules=dict(),
            ec2_url=dict(aliases=['EC2_URL']),
            ec2_secret_key=dict(aliases=['EC2_SECRET_KEY', 'aws_secret_key'], no_log=True),
            ec2_access_key=dict(aliases=['EC2_ACCESS_KEY', 'aws_access_key']),
            region=dict(choices=['eu-west-1', 'sa-east-1', 'us-east-1', 'ap-northeast-1', 'us-west-2', 'us-west-1', 'ap-southeast-1', 'ap-southeast-2']),
            state = dict(default='present', choices=['present', 'absent']),
        ),
        supports_check_mode=True,
    )

    # def get_ec2_creds(module):
    #   return ec2_url, ec2_access_key, ec2_secret_key, region
    ec2_url, ec2_access_key, ec2_secret_key, region = get_ec2_creds(module)

    name = module.params['name']
    description = module.params['description']
    vpc_id = module.params['vpc_id']
    rules = module.params['rules']
    state = module.params.get('state')

    changed = False

    # If we have a region specified, connect to its endpoint.
    if region:
        try:
            ec2 = boto.ec2.connect_to_region(region, aws_access_key_id=ec2_access_key, aws_secret_access_key=ec2_secret_key)
        except boto.exception.NoAuthHandlerFound, e:
            module.fail_json(msg=str(e))
    # Otherwise, no region so we fallback to the old connection method
    else:
        try:
            if ec2_url:  # if we have an URL set, connect to the specified endpoint
                ec2 = boto.connect_ec2_endpoint(ec2_url, ec2_access_key, ec2_secret_key)
            else:  # otherwise it's Amazon.
                ec2 = boto.connect_ec2(ec2_access_key, ec2_secret_key)
        except boto.exception.NoAuthHandlerFound, e:
            module.fail_json(msg=str(e))

    # find the group if present
    group = None
    groups = {}
    for curGroup in ec2.get_all_security_groups():
        groups[curGroup.id] = curGroup

        if curGroup.name == name and curGroup.vpc_id == vpc_id:
            group = curGroup

    # Ensure requested group is absent
    if state == 'absent':
        if group:
            '''found a match, delete it'''
            try:
                group.delete()
            except Exception, e:
                module.fail_json(msg="Unable to delete security group '%s' - %s" % (group, e))
            else:
                group = None
                changed = True
        else:
            '''no match found, no changes required'''

    # Ensure requested group is present
    elif state == 'present':
        if group:
            '''existing group found'''
            # check the group parameters are correct
            group_in_use = False
            rs = ec2.get_all_instances()
            for r in rs:
                for i in r.instances:
                    group_in_use |= reduce(lambda x, y: x | (y.name == 'public-ssh'), i.groups, False)

            if group.description != description:
                if group_in_use:
                    module.fail_json(msg="Group description does not match, but it is in use so cannot be changed.")

        # if the group doesn't exist, create it now
        else:
            '''no match found, create it'''
            if not module.check_mode:
                group = ec2.create_security_group(name, description, vpc_id=vpc_id)
            changed = True
    else:
        module.fail_json(msg="Unsupported state requested: %s" % state)

    # create a lookup for all existing rules on the group
    if group:
        groupRules = {}
        addRulesToLookup(group.rules, 'in', groupRules)

        # Now, go through all provided rules and ensure they are there.
        if rules:
            for rule in rules:
                group_id = None
                ip = None
                if 'group_id' in rule and 'cidr_ip' in rule:
                    module.fail_json(msg="Specify group_id OR cidr_ip, not both")
                elif 'group_id' in rule:
                    group_id = rule['group_id']
                elif 'cidr_ip' in rule:
                    ip = rule['cidr_ip']

                if rule['proto'] == 'all':
                    rule['proto'] = -1
                    rule['from_port'] = None
                    rule['to_port'] = None

                # If rule already exists, don't later delete it
                ruleId = "%s-%s-%s-%s-%s-%s" % ('in', rule['proto'], rule['from_port'], rule['to_port'], group_id, ip)
                if ruleId in groupRules:
                    del groupRules[ruleId]
                # Otherwise, add new rule
                else:
                    grantGroup = None
                    if group_id:
                        grantGroup = groups[group_id]

                    if not module.check_mode:
                        group.authorize(rule['proto'], rule['from_port'], rule['to_port'], ip, grantGroup)
                    changed = True

        # Finally, remove anything left in the groupRules -- these will be defunct rules
        for rule in groupRules.itervalues():
            for grant in rule.grants:
                grantGroup = None
                if grant.group_id:
                    grantGroup = groups[grant.group_id]
                if not module.check_mode:
                    group.revoke(rule.ip_protocol, rule.from_port, rule.to_port, grant.cidr_ip, grantGroup)
                changed = True

    if group:
        module.exit_json(changed=changed, group_id=group.id)
    else:
        module.exit_json(changed=changed, group_id=None)

# import module snippets
from ansible.module_utils.basic import *
from ansible.module_utils.ec2 import *

main()
