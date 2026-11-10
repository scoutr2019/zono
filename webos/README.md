# Zono for LG TV (webOS)

The LG version of Zono: the same screens, rules and four languages as the Android TV app, as a webOS web app
(plain HTML/CSS/JavaScript, no framework). Works with the remote's arrows / OK / Back, CH+/CH−, the play buttons
and the Magic Remote pointer. Video plays in the TV's own player (HLS, MPEG-TS, MKV, MP4).

## Build

    npm install -g @webos-tools/cli
    ./build.sh                       # -> dist/be.zono.tv_<version>_all.ipk (scripts are minified)

## Tests

    node --test tests/catalog.test.js                    # Xtream / M3U / 4K rules
    node tests/e2e.js <video.webm> <screenshot folder>   # whole app with the remote's keys, fake provider (needs Playwright)
    ZONO_ROOT=<unpacked ipk app folder> node tests/e2e.js ...   # the same against the packaged app

## Install on an LG TV without the store (free)

1. Make a free account on https://webostv.developer.lge.com.
2. On the TV, install **Developer Mode** from the LG Content Store, sign in, switch Dev Mode on (the TV restarts),
   then switch **Key Server** on.
3. On a PC in the same network, install **webOS Dev Manager** (https://github.com/webosbrew/dev-manager-desktop),
   add the TV (its IP address and the passphrase shown in the Developer Mode app) and install the .ipk.

Developer Mode runs for 50 hours at a time; press "Extend" in the Developer Mode app to keep it.
