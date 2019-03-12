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
		'staff': nf.icons['mdi-wrench'],
		'admin': nf.icons['mdi-shield'],
		'broadcaster': nf.icons['fa-video_camera'],
		'moderator': nf.icons['mdi-sword'],
		'verified': nf.icons['oct-verified'],
		'vip': nf.icons['fa-diamond'],
		'turbo': nf.icons['mdi-battery_charging'],
		'prime': nf.icons['mdi-crown'],
	})
except:
	print('Nerdfonts package not available, falling back to ascii symbols')
