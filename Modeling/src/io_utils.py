"""
IO functions for importing and exporting label maps and mesh surfaces

@author: Fanwei Kong

"""
import numpy as np
import os
import vtk

def read_label_map(fn):
    """ 
    This function imports the label map as vtk image.

    Args: 
        fn: filename of the label map

    Return:
        label: label map as a vtk image
    """
    _, ext = fn.split(os.extsep, 1)  

    if fn[-3:]=='vti':
        reader = vtk.vtkXMLImageDataReader()
        reader.SetFileName(fn)
        reader.Update()
        label = reader.GetOutput()
    elif ext[-3:]=='nii' or ext[-6:]=='nii.gz':
        reader = vtk.vtkNIFTIImageReader()
        reader.SetFileName(fn)
        reader.Update()

        image = reader.GetOutput()
        matrix = reader.GetQFormMatrix()
        if matrix is None:
            matrix = reader.GetSFormMatrix()
        matrix.Invert()
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(image)
        reslice.SetResliceAxes(matrix)
        reslice.SetInterpolationModeToNearestNeighbor()
        reslice.Update()
        reslice2 = vtk.vtkImageReslice()
        reslice2.SetInputData(reslice.GetOutput())
        matrix = vtk.vtkMatrix4x4()
        for i in range(4):
            matrix.SetElement(i,i,1)
        matrix.SetElement(0,0,-1)
        matrix.SetElement(1,1,-1)
        reslice2.SetResliceAxes(matrix)
        reslice2.SetInterpolationModeToNearestNeighbor()
        reslice2.Update()
        label = reslice2.GetOutput()
    else:
        raise IOError("File extension is not recognized")
    
    return label


def vtk_image_to_sitk_image(vtkIm):
    """ 
    Converts VTK image to Sitk image

    NOTE: ONLY WORK FOR IDENTITY DIRECTION MATRIX

    """
    import SimpleITK as sitk
    from vtk.util.numpy_support import vtk_to_numpy
    py_im = vtk_to_numpy(vtkIm.GetPointData().GetScalars())
    x , y, z = vtkIm.GetDimensions()
    out_im = sitk.GetImageFromArray(py_im.reshape(z, y, x))
    out_im.SetSpacing(vtkIm.GetSpacing())
    out_im.SetOrigin(vtkIm.GetOrigin())
    out_im.SetDirection(np.eye(3).flatten())
    return out_im


def write_vtk_polydata(poly, fn):
    """
    This function writes a vtk polydata to disk
    Args:
        poly: vtk polydata
        fn: file name
    Returns:
        None
    """
    
    print('Writing vtp with name:', fn)
    if (fn == ''):
        return 0

    _ , extension = os.path.splitext(fn)

    if extension == '.vtk':
        writer = vtk.vtkPolyDataWriter()
    elif extension == '.vtp':
        writer = vtk.vtkXMLPolyDataWriter()
    else:
        raise ValueError("Incorrect extension"+extension)
    writer.SetInputData(poly)
    writer.SetFileName(fn)
    writer.Update()
    writer.Write()
    return

def write_vtk_image(vtkIm, fn):
    """
    This function writes a vtk image to disk
    Args:
        vtkIm: the vtk image to write
        fn: file name
    Returns:
        None
    """
    print("Writing vti with name: ", fn)

    _, extension = os.path.splitext(fn)
    if extension == '.vti':
        writer = vtk.vtkXMLImageDataWriter()
    elif extension == '.mhd':
        writer = vtk.vtkMetaImageWriter()
    else:
        raise ValueError("Incorrect extension " + extension)
    writer.SetInputData(vtkIm)
    writer.SetFileName(fn)
    writer.Update()
    writer.Write()
    return

def numpy_array_to_vtk_image(img):
    """
    This function creates a vtk image from a python array

    Args:
        img: python ndarray of the image
    Returns:
        imageData: vtk image
    """
    from vtk.util.numpy_support import numpy_to_vtk, get_vtk_array_type
    
    #vtkArray = numpy_to_vtk(num_array=img.flatten('F'), deep=True, array_type=get_vtk_array_type(img.dtype))
    vtkArray = numpy_to_vtk(img.transpose(0,1,2).flatten())
    return vtkArray


def read_vtk_mesh(fileName):
    """
    Loads surface/volume mesh to VTK
    """
    if (fileName == ''):
        return 0
    fn_dir, fn_ext = os.path.splitext(fileName)
    if (fn_ext == '.vtk'):
        print('Reading vtk with name: ', fileName)
        reader = vtk.vtkPolyDataReader()
    elif (fn_ext == '.vtp'):
        print('Reading vtp with name: ', fileName)
        reader = vtk.vtkXMLPolyDataReader()
    elif (fn_ext == '.stl'):
        print('Reading stl with name: ', fileName)
        reader = vtk.vtkSTLReader()
    elif (fn_ext == '.vtu'):
        print('Reading vtu with name: ', fileName)
        reader = vtk.vtkXMLUnstructuredGridReader()
    elif (fn_ext == '.pvtu'):
        print('Reading pvtu with name: ', fileName)
        reader = vtk.vtkXMLPUnstructuredGridReader()
    else:
        raise ValueError('File extension not supported')

    reader.SetFileName(fileName)
    reader.Update()
    return reader.GetOutput()

def write_vtu_file(ug, fn):
    print('Writing vts with name:', fn)
    if (fn == ''):
        raise ValueError('File name is empty')
    writer = vtk.vtkXMLUnstructuredGridWriter()
    writer.SetInputData(ug)
    writer.SetFileName(fn)
    writer.Update()
    writer.Write()

def write_point_cloud(pts,fn):
    """
    Write VTK points to Elastix point format
    """
    with open(fn,'w') as f:
        f.write('point\n')
        f.write('%d\n' % pts.GetNumberOfPoints())
        for i in range(pts.GetNumberOfPoints()):
            pt = pts.GetPoint(i)
            f.write('%f %f %f\n' % (pt[0], pt[1], pt[2]))

    return

def write_vtk_polydataVerts(poly, fn):
    """
    Writes the vertices of the VTK PolyData
    """
    print('Writing pts with name: ', fn)
    pts = poly.GetPoints()
    write_point_cloud(pts, fn)
    return

def read_elastix_point_ouptut(fn):
    """
    Read the point coordinates after registration generated by Elastix

    Args: 
        fn: file name
    Returns:
        pts: vtk 
    """
    import re
    pts = vtk.vtkPoints()
    with open(fn, 'r') as f:
        for line in f:
            s = re.findall(r'[+-]?\d+(?:\.\d+)?', line)
            if len(s)>0:
                s = s[10:13]
                pts.InsertNextPoint([float(i) for i in s])

    print('Reading %d points from file %s' % (pts.GetNumberOfPoints(), fn))
    return pts

