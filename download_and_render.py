"""
This script downloads data from a specified URL and renders it in 3D using a single 3D view layout in 3D Slicer.

Default URL: https://raw.githubusercontent.com/SlicerMorph/SampleData/refs/heads/master/IMPC_sample_data.nrrd
"""

import slicer
import SampleData

# Define the URL for the data
url = "https://raw.githubusercontent.com/SlicerMorph/SampleData/refs/heads/master/IMPC_sample_data.nrrd"

# Step 1: Download the data
print("Downloading data from URL...")
try:
    volume_node = SampleData.downloadFromURL(urls=[url])[0]  # Get the first node from the returned list
    print(f"Data downloaded successfully. Node name: {volume_node.GetName()}")
except Exception as e:
    print(f"❌ Failed to download data: {e}")
    raise

# Step 2: Set up the 3D view layout
print("Setting up 3D view layout...")
try:
    slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
    print("3D view layout set successfully.")
except Exception as e:
    print(f"❌ Failed to set 3D view layout: {e}")
    raise

# Step 3: Center the 3D view on the loaded volume
print("Centering 3D view on the loaded volume...")
try:
    slicer.util.resetThreeDViews()
    print("3D view centered successfully.")
except Exception as e:
    print(f"❌ Failed to center 3D view: {e}")
    raise

print("✅ Script completed successfully. The data is now rendered in the 3D view.")