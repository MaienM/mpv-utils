BADGES = {
	'staff': '~',
	'admin': '&',
	'broadcaster': '@',
	'moderator': '%',
	'subscriber': '+',
}

try:
	import nerdfonts

	BADGES.update({
		'staff': nerdfonts.icons['mdi_wrench'],
		'admin': nerdfonts.icons['mdi_shield'],
		'broadcaster': nerdfonts.icons['fa_video_camera'],
		'moderator': nerdfonts.icons['mdi_sword_cross'],
		'subscriber': nerdfonts.icons['fa_star'],
		'verified': nerdfonts.icons['oct_verified'],
		'vip': nerdfonts.icons['fa_diamond'],
		'turbo': nerdfonts.icons['mdi_battery_charging'],
		'prime': nerdfonts.icons['mdi_crown'],
	})
except ImportError:
	print('Nerdfonts package not available, falling back to ascii symbols')
