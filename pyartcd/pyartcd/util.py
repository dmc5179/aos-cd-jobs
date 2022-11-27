import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple
import logging

import aiofiles
import yaml

from doozerlib import assembly, model, util as doozerutil
from pyartcd import exectools

logger = logging.getLogger(__name__)


def isolate_el_version_in_release(release: str) -> Optional[int]:
    """
    Given a release field, determines whether is contains
    a RHEL version. If it does, it returns the version value as int.
    If it is not found, None is returned.
    """
    match = re.match(r'.*\.el(\d+)(?:\.+|$)', release)
    if match:
        return int(match.group(1))

    return None


def isolate_el_version_in_branch(branch_name: str) -> Optional[int]:
    """
    Given a distgit branch name, determines whether is contains
    a RHEL version. If it does, it returns the version value as int.
    If it is not found, None is returned.
    """
    match = re.fullmatch(r'.*rhel-(\d+).*', branch_name)
    if match:
        return int(match.group(1))

    return None


def isolate_major_minor_in_group(group_name: str) -> Tuple[int, int]:
    """
    Given a group name, determines whether is contains
    a OCP major.minor version. If it does, it returns the version value as (int, int).
    If it is not found, (None, None) is returned.
    """
    match = re.fullmatch(r"openshift-(\d+).(\d+)", group_name)
    if not match:
        return None, None
    return int(match[1]), int(match[2])


async def load_group_config(group: str, assembly: str, env=None) -> Dict:
    cmd = [
        "doozer",
        "--group", group,
        "--assembly", assembly,
        "config:read-group",
        "--yaml",
    ]
    if env is None:
        env = os.environ.copy()
    _, stdout, _ = await exectools.cmd_gather_async(cmd, stderr=None, env=env)
    group_config = yaml.safe_load(stdout)
    if not isinstance(group_config, dict):
        raise ValueError("ocp-build-data contains invalid group config.")
    return group_config


async def load_releases_config(build_data_path: os.PathLike) -> Optional[Dict]:
    try:
        async with aiofiles.open(Path(build_data_path) / "releases.yml", "r") as f:
            content = await f.read()
        return yaml.safe_load(content)
    except FileNotFoundError:
        return None


def get_assembly_type(releases_config: Dict, assembly_name: str):
    return assembly.assembly_type(model.Model(releases_config), assembly_name)


def get_assembly_basis(releases_config: Dict, assembly_name: str):
    return assembly.assembly_basis(model.Model(releases_config), assembly_name)


def get_assembly_promotion_permits(releases_config: Dict, assembly_name: str):
    return assembly._assembly_config_struct(model.Model(releases_config), assembly_name, 'promotion_permits', [])


def get_release_name_for_assembly(group_name: str, releases_config: Dict, assembly_name: str):
    return doozerutil.get_release_name_for_assembly(group_name, model.Model(releases_config), assembly_name)


async def kinit():
    logger.info('Initializing ocp-build kerberos credentials')

    # The '-f' ensures that the ticket is forwarded to remote hosts
    # when using SSH. This is required for when we build signed
    # puddles.
    cmd = [
        'kinit',
        '-f',
        '-k',
        '-t',
        '/home/jenkins/exd-ocp-buildvm-bot-prod.keytab',
        'exd-ocp-buildvm-bot-prod@IPA.REDHAT.COM'
    ]
    await exectools.cmd_assert_async(cmd)


async def branch_arches(branch: str, ga_only: bool = False):
    """
    Find the supported arches for a specific release
    :param branch: The name of the branch to get configs for. For example: 'openshift-4.12
    :ga_only: If you only want group arches and do not care about arches_override.
    :return: A list of the arches built for this branch
    """

    logger.info('Fetching group config for %s', branch)

    # Check if arches_override has been specified. This is used in group.yaml
    # when we temporarily want to build for CPU architectures that are not yet GA.
    cmd = f"doozer --group={branch} config:read-group --yaml arches_override --default '[]'"
    _, out, _ = await exectools.cmd_gather_async(cmd)
    arches_override_list = yaml.safe_load(out)
    if ga_only and arches_override_list:
        return arches_override_list

    # Read supported arches from group config
    cmd = f'doozer --group={branch} config:read-group --yaml arches'
    _, out, _ = await exectools.cmd_gather_async(cmd)
    arches = yaml.safe_load(out)
    return arches
