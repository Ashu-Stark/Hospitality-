"""Sign in · join with an invite code · one-click demo accounts."""

from lib import login_ui, platform, wake

wake.ensure_awake(platform.mode())  # 'Waking up the server…' while a sleeping platform API starts
login_ui.render()
