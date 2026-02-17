# PPA Installation Guide

This guide explains how to publish Hotspot Manager to a PPA (Personal Package Archive) for easy apt installation.

## Prerequisites

1. **Launchpad Account**: Create one at https://launchpad.net
2. **GPG Key**: Required for signing packages

## Setup GPG Key

```bash
# Generate GPG key
gpg --full-generate-key
# Choose RSA (4096 bits), expiration as needed

# Upload to Ubuntu keyserver
gpg --send-keys --keyserver keyserver.ubuntu.com YOUR_KEY_ID

# Find your key ID
gpg --list-keys
```

## Create PPA on Launchpad

1. Go to https://launchpad.net/~YOUR_USERNAME
2. Click "Create a new PPA"
3. Name it "hotspot-manager"
4. Add description: "Concurrent WiFi + Hotspot Manager for Linux"

## Configure Git for Signing

```bash
# Tell git to use your GPG key
git config --global user.signingkey YOUR_KEY_ID
git config --global commit.gpgsign true
```

## Configure GitHub Secrets

Add these secrets to your GitHub repository (Settings > Secrets):

1. `GPG_PRIVATE_KEY` - Export your GPG private key:
   ```bash
   gpg --armor --export-secret-keys YOUR_KEY_ID
   ```

2. `GPG_PASSPHRASE` - Your GPG key passphrase

3. `PPA_NAME` - Your PPA name (e.g., `davytheprogrammer/hotspot-manager`)

## Manual PPA Upload

If you prefer manual upload:

```bash
# Install tools
sudo apt install devscripts dput-ng

# Build source package
debuild -S -sa

# Upload to PPA
dput ppa:YOUR_USERNAME/hotspot-manager ../hotspot-manager_*.changes
```

## Users Can Then Install

```bash
sudo add-apt-repository ppa:YOUR_USERNAME/hotspot-manager
sudo apt update
sudo apt install hotspot-manager
```

## Automation

The GitHub workflow `.github/workflows/ppa.yml` handles automatic PPA uploads when you create a release tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```