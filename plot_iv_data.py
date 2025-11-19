"""
Plot I-V curve data from exported txt file using matplotlib
Usage: python plot_iv_data.py <data_file.txt>
"""

import sys
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np

def read_iv_data(filename):
    """Read I-V data from txt file"""
    data = np.loadtxt(filename, skiprows=1)  # Skip header line
    
    voltage = data[:, 0]
    total_current = data[:, 1]
    ion_current = data[:, 2]
    electron_current = data[:, 3]
    
    return voltage, total_current, ion_current, electron_current

def plot_iv_curve(voltage, total_current, ion_current, electron_current, filename):
    """Create I-V curve plots"""
    
    # Create figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))
    
    # Plot 1: Full I-V Characteristic Curve
    ax1.plot(voltage, total_current * 1e3, 'b-', linewidth=2, label='Total Current', alpha=0.8)
    ax1.plot(voltage, electron_current * 1e3, 'r-', linewidth=1.5, label='Electron Current', alpha=0.7)
    ax1.plot(voltage, ion_current * 1e3, 'g-', linewidth=1.5, label='Ion Current', alpha=0.7)
    
    ax1.set_xlabel('Probe Voltage (V)', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Current (mA)', fontsize=12, fontweight='bold')
    ax1.set_title('Langmuir Probe I-V Characteristic Curve', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3, linestyle='--')
    ax1.legend(loc='best', fontsize=10)
    ax1.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
    ax1.axvline(x=0, color='k', linestyle='-', linewidth=0.5)
    
    # Plot 2: RF Cycles Detail with full-resolution data
    ax2.plot(voltage, total_current * 1e3, 'b-', linewidth=1.2, label='Total Current', alpha=0.85)
    ax2.plot(voltage, electron_current * 1e3, 'r-', linewidth=1, label='Electron Current', alpha=0.7)
    ax2.plot(voltage, ion_current * 1e3, 'g-', linewidth=1, label='Ion Current', alpha=0.7)
    ax2.set_xlabel('Probe Voltage (V)', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Current (mA)', fontsize=12, fontweight='bold')
    ax2.set_title(f'RF Oscillation Detail (all {len(voltage)} samples)', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3, linestyle='--')
    ax2.legend(loc='best', fontsize=10)
    
    plt.tight_layout()
    
    # Save figure
    output_file = Path(filename).stem + '_plot.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Plot saved to: {output_file}")
    
    # Show plot
    plt.show()

def print_statistics(voltage, total_current, ion_current, electron_current):
    """Print data statistics"""
    print("\n" + "="*60)
    print("DATA STATISTICS")
    print("="*60)
    print(f"Total points: {len(voltage)}")
    print(f"Voltage range: {voltage.min():.2f} V to {voltage.max():.2f} V")
    print(f"Total current range: {total_current.min()*1e3:.4f} mA to {total_current.max()*1e3:.4f} mA")
    print(f"Electron current range: {electron_current.min()*1e3:.4f} mA to {electron_current.max()*1e3:.4f} mA")
    print(f"Ion current range: {ion_current.min()*1e3:.4f} mA to {ion_current.max()*1e3:.4f} mA")
    
    # Find floating potential (where I_total ≈ 0)
    zero_crossing_idx = np.argmin(np.abs(total_current))
    vf = voltage[zero_crossing_idx]
    print(f"\nEstimated floating potential: {vf:.2f} V")
    print("="*60 + "\n")

def _select_file_via_dialog() -> Optional[Path]:
    """Open a file selection dialog (if tkinter is available)."""
    try:
        from tkinter import Tk, filedialog  # type: ignore
    except Exception as exc:  # pragma: no cover - only hit on headless env
        print(f"File dialog unavailable ({exc}); please pass a filename.")
        return None

    root = Tk()
    root.withdraw()
    root.update()
    filename = filedialog.askopenfilename(
        title="Select Langmuir I-V data file",
        filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
    )
    root.destroy()
    return Path(filename) if filename else None

def main():
    if len(sys.argv) < 2:
        print("Usage: python plot_iv_data.py <data_file.txt>")
        print("No filename provided—opening file chooser...")
        selected = _select_file_via_dialog()
        if selected is None:
            print("\nLooking for .txt files in current directory:")
            txt_files = list(Path('.').glob('*.txt'))
            if txt_files:
                for f in txt_files:
                    print(f"  - {f}")
                print(f"\nTry: python plot_iv_data.py {txt_files[0]}")
            else:
                print("  No .txt files found")
            sys.exit(1)
        filename = str(selected)
    else:
        filename = sys.argv[1]

    if not Path(filename).exists():
        print(f"Error: File '{filename}' not found")
        sys.exit(1)
    
    print(f"\nReading data from: {filename}")
    
    try:
        voltage, total_current, ion_current, electron_current = read_iv_data(filename)
        print_statistics(voltage, total_current, ion_current, electron_current)
        plot_iv_curve(voltage, total_current, ion_current, electron_current, filename)
    except Exception as e:
        print(f"Error reading or plotting data: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
