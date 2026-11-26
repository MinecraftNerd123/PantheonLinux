PREFIX ?= /usr/local
CC ?= cc
NATIVE = pantheon/native/libpantheon-native.so

all: $(NATIVE)

$(NATIVE): pantheon/native/findtext.c
	$(CC) -O2 -shared -fPIC -o $@ $<

test: $(NATIVE)
	python3 -m unittest discover -s tests -p 'test_*.py'
	node --test tests/*.test.cjs

run: $(NATIVE)
	./bin/pantheon

install: $(NATIVE)
	install -d $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/framework $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/platform $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/native
	install -m644 pantheon/*.py pantheon/bridge.js $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/
	install -m644 pantheon/framework/*.py $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/framework/
	install -m644 pantheon/platform/*.py $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/platform/
	install -m755 $(NATIVE) $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/native/
	install -m644 pantheon/native/findtext.c $(DESTDIR)$(PREFIX)/share/pantheon/pantheon/native/
	install -d $(DESTDIR)$(PREFIX)/share/pantheon/Lib $(DESTDIR)$(PREFIX)/share/pantheon/macros
	cp -r Lib/ui $(DESTDIR)$(PREFIX)/share/pantheon/Lib/
	install -m644 macros/*.json $(DESTDIR)$(PREFIX)/share/pantheon/macros/
	install -d $(DESTDIR)$(PREFIX)/bin
	printf '#!/bin/sh\nPYTHONPATH="%s/share/pantheon$${PYTHONPATH:+:$$PYTHONPATH}" exec python3 -m pantheon "$$@"\n' "$(PREFIX)" > $(DESTDIR)$(PREFIX)/bin/pantheon
	chmod 755 $(DESTDIR)$(PREFIX)/bin/pantheon
	install -Dm644 packaging/$(APP_ID).desktop $(DESTDIR)$(PREFIX)/share/applications/$(APP_ID).desktop
	install -Dm644 packaging/$(APP_ID).metainfo.xml $(DESTDIR)$(PREFIX)/share/metainfo/$(APP_ID).metainfo.xml
	install -Dm644 Lib/ui/assets/pantheon.png $(DESTDIR)$(PREFIX)/share/icons/hicolor/128x128/apps/$(APP_ID).png

APP_ID = io.github.MinecraftNerd123.PantheonLinux

flatpak:
	flatpak-builder --user --install --force-clean --install-deps-from=flathub build-dir packaging/flatpak/$(APP_ID).yml

bundle:
	flatpak-builder --force-clean --repo=repo --install-deps-from=flathub build-dir packaging/flatpak/$(APP_ID).yml
	flatpak build-bundle repo dist/Pantheon.flatpak $(APP_ID)

clean:
	rm -rf build-dir repo .flatpak-builder $(NATIVE)

.PHONY: all test run install flatpak bundle clean
