from amdm_interactive.envs.target import FacingTargetEnv
from amdm_interactive.envs.path import FacingPathEnv
from amdm_interactive.envs.joystick import JoystickEnv, XboxCommand

__all__ = ['FacingTargetEnv', 'FacingPathEnv', 'JoystickEnv', 'XboxCommand', 'ENVS']

ENVS = {'target': FacingTargetEnv, 'path': FacingPathEnv, 'joystick': JoystickEnv}
