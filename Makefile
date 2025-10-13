PYTHON ?= python3

.PHONY: macos-app clean

macos-app:
	@echo "Building Anki JP Deck Builder macOS app bundle..."
	$(PYTHON) -m PyInstaller --clean --noconfirm mac_gui_app.spec

clean:
	@echo "Removing build artifacts..."
	rm -rf build dist __pycache__
