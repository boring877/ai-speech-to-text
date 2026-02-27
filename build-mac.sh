#!/bin/bash

# Voice Type - Mac Build Script
# Run this script on a Mac to build the VoiceType.app and create an easy PKG installer

echo "Building Voice Type for macOS..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required. Please install it first."
    exit 1
fi

# Create virtual environment (optional but recommended)
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt
pip install pyinstaller

# Build the app
echo "Building VoiceType.app..."
pyinstaller VoiceType-Mac.spec --noconfirm

# Check if build was successful
if [ -d "dist/VoiceType.app" ]; then
    echo ""
    echo "App build successful!"
    
    # Create PKG installer (easiest for users - just double-click and Install)
    echo "Creating PKG installer..."
    
    # Remove old installers if exist
    rm -f dist/VoiceType.pkg
    rm -f dist/VoiceType.dmg
    
    # Create a temporary root folder for pkgbuild
    PKG_ROOT="dist/pkg_root"
    rm -rf "$PKG_ROOT"
    mkdir -p "$PKG_ROOT/Applications"
    
    # Copy app to the Applications folder in pkg root
    cp -R dist/VoiceType.app "$PKG_ROOT/Applications/"
    
    # Build the PKG installer
    pkgbuild --root "$PKG_ROOT" \
        --identifier com.voicetype.app \
        --version 1.0 \
        --install-location / \
        dist/VoiceType.pkg
    
    # Clean up temp folder
    rm -rf "$PKG_ROOT"
    
    echo ""
    echo "=========================================="
    echo "Build complete!"
    echo "=========================================="
    echo ""
    echo "Created files:"
    echo "  - dist/VoiceType.app (application bundle)"
    echo "  - dist/VoiceType.pkg (PKG installer - DISTRIBUTE THIS)"
    echo ""
    echo "For users - SUPER SIMPLE:"
    echo "  1. Download VoiceType.pkg"
    echo "  2. Double-click it"
    echo "  3. Click Continue, then Install"
    echo "  4. Done! VoiceType is in Applications"
    echo ""
else
    echo "Build failed. Check the error messages above."
    exit 1
fi
