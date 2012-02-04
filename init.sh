[ -n "$BASH" -o -n "$ZSH_VERSION" ] || return

if [ -n "$BASH" ]; then
	function 0path { eval "$(0launch 'http://gfxmonk.net/dist/0install/0path.xml' "$@")" }
fi
if [ -n "$ZSH_VERSION" ]; then
	function 0path { eval "$(0launch 'http://gfxmonk.net/dist/0install/0path.xml' $@)" }
fi

