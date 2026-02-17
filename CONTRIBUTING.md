# Contributing to Hotspot Manager

Thank you for your interest in contributing! 🎉

## Ways to Contribute

- 🐛 **Report bugs** - Open an issue with details
- 💡 **Suggest features** - Open an issue with the "enhancement" label
- 📝 **Improve documentation** - Submit a PR
- 🔧 **Submit code** - See below

## Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/hotspot-manager.git
cd hotspot-manager

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e .

# Run the app
python3 run.py
```

## Pull Request Process

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Test thoroughly on Linux
4. Update README if needed
5. Submit PR with a clear description

## Code Style

- Follow PEP 8 for Python
- Use meaningful variable names
- Add comments for complex logic
- Keep functions focused and small

## Testing

Before submitting:
```bash
# Test GUI
python3 run.py

# Test CLI
python3 -m hotspot_manager.cli status
python3 -m hotspot_manager.cli interfaces
```

## Questions?

Open an issue or email davisogega8@gmail.com