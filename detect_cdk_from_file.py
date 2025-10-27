"""
Simple CDK File Detector

Given a file path (from git diff), determine if it's part of a CDK app.
If yes, return the CDK app root directory where you should run cdk synth.

Usage:
    result = is_cdk_file('path/to/file.py')
    if result['is_cdk']:
        subprocess.run(['cdk', 'synth'], cwd=result['cdk_root'])
"""

import json
from pathlib import Path
from typing import Dict, Optional


def is_cdk_file(file_path: str) -> Dict:
    """
    Check if a file is part of a CDK app.
    
    Args:
        file_path: Path to a file (from git diff)
        
    Returns:
        {
            'is_cdk': bool,
            'cdk_root': str or None,    # Directory to run cdk synth from
            'file_path': str,
            'language': str or None      # python, typescript, javascript, java, csharp, go
        }
    """
    file_path = Path(file_path)
    
    # Quick check: Is this a CDK-related file extension?
    if not _is_cdk_language(file_path):
        return {
            'is_cdk': False,
            'cdk_root': None,
            'file_path': str(file_path),
            'language': None
        }
    
    # Search upward for CDK app root
    cdk_root = _find_cdk_root(file_path)
    
    if not cdk_root:
        return {
            'is_cdk': False,
            'cdk_root': None,
            'file_path': str(file_path),
            'language': None
        }
    
    # Detect language
    language = _detect_language(cdk_root)
    
    return {
        'is_cdk': True,
        'cdk_root': str(cdk_root),
        'file_path': str(file_path),
        'language': language
    }


def _is_cdk_language(file_path: Path) -> bool:
    """Check if file extension could be CDK-related."""
    cdk_extensions = {'.py', '.ts', '.js', '.mjs', '.java', '.cs', '.go'}
    return file_path.suffix in cdk_extensions


def _find_cdk_root(file_path: Path) -> Optional[Path]:
    """
    Search upward from file to find CDK app root.
    Returns the directory containing cdk.json (or similar indicators).
    """
    # Start from file's directory
    current = file_path.parent if file_path.is_file() else file_path
    
    # Search up to 5 levels
    for _ in range(5):
        # Check for cdk.json (most reliable)
        if (current / 'cdk.json').exists():
            return current
        
        # Check for cdk.context.json
        if (current / 'cdk.context.json').exists():
            return current
        
        # Check for CDK project structure
        if _has_cdk_structure(current):
            return current
        
        # Move up one directory
        parent = current.parent
        if parent == current:  # Reached filesystem root
            break
        current = parent
    
    return None


def _has_cdk_structure(directory: Path) -> bool:
    """Check if directory has structure indicating CDK app."""
    # Python CDK: app.py + requirements.txt with aws-cdk
    if (directory / 'app.py').exists() or (directory / 'cdk.py').exists():
        req_file = directory / 'requirements.txt'
        if req_file.exists():
            try:
                content = req_file.read_text()
                if 'aws-cdk' in content:
                    return True
            except:
                pass
    
    # TypeScript/JavaScript CDK: package.json with aws-cdk-lib
    pkg_json = directory / 'package.json'
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text())
            deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
            if any('aws-cdk' in dep for dep in deps.keys()):
                return True
        except:
            pass
    
    # Java CDK: pom.xml with software.amazon.awscdk
    pom = directory / 'pom.xml'
    if pom.exists():
        try:
            if 'software.amazon.awscdk' in pom.read_text():
                return True
        except:
            pass
    
    # Go CDK: go.mod with github.com/aws/aws-cdk-go
    gomod = directory / 'go.mod'
    if gomod.exists():
        try:
            if 'github.com/aws/aws-cdk-go' in gomod.read_text():
                return True
        except:
            pass
    
    # C# CDK: .csproj with Amazon.CDK
    for csproj in directory.glob('*.csproj'):
        try:
            if 'Amazon.CDK' in csproj.read_text():
                return True
        except:
            pass
    
    return False


def _detect_language(cdk_root: Path) -> str:
    """Detect the CDK app language."""
    # Check for language-specific files
    if (cdk_root / 'requirements.txt').exists() or (cdk_root / 'setup.py').exists():
        return 'python'
    
    if (cdk_root / 'package.json').exists():
        if (cdk_root / 'tsconfig.json').exists():
            return 'typescript'
        return 'javascript'
    
    if (cdk_root / 'pom.xml').exists() or (cdk_root / 'build.gradle').exists():
        return 'java'
    
    if list(cdk_root.glob('*.csproj')) or list(cdk_root.glob('*.sln')):
        return 'csharp'
    
    if (cdk_root / 'go.mod').exists():
        return 'go'
    
    return 'unknown'


# Example usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python detect_cdk_from_file.py <file_path>")
        print("\nExample:")
        print("  python detect_cdk_from_file.py app.py")
        print("  python detect_cdk_from_file.py src/stack.ts")
        sys.exit(1)
    
    file_path = sys.argv[1]
    result = is_cdk_file(file_path)
    
    print(f"File: {file_path}")
    print("-" * 60)
    
    if result['is_cdk']:
        print("✅ CDK File Detected")
        print(f"   CDK Root: {result['cdk_root']}")
        print(f"   Language: {result['language']}")
        print(f"\n💡 To synthesize:")
        print(f"   cd {result['cdk_root']}")
        print(f"   cdk synth")
    else:
        print("❌ Not a CDK File")
        print("   This is a regular file, not part of a CDK app")

