#!/usr/bin/env python

"""Extracts per-slice surface contours from a binary object image."""

# build-in modules
import argparse
import logging
import os

# third-party modules
import scipy.ndimage
from nibabel.loadsave import load
from nibabel.spatialimages import ImageFileError

# path changes

# own modules
from medpy.core import Logger
from medpy.core.exceptions import ArgumentError
import math


# information
__author__ = "Oskar Maier"
__version__ = "r1.0, 2012-04-25"
__email__ = "oskar.maier@googlemail.com"
__status__ = "Release"
__description__ = """
                  Extracts per-slice surface contours from a binary object image.
                  Takes as input a binary image, extracts the surface of the contained
                  foreground object and saves them per-slice (in the supplied dimension)
                  in the supplied folder.
                  Note: Also performs some morphological operations on the masks.
                  """

# code
def main():
    # parse cmd arguments
    parser = getParser()
    parser.parse_args()
    args = getArguments(parser)
    
    # prepare logger
    logger = Logger.getInstance()
    if args.debug: logger.setLevel(logging.DEBUG)
    elif args.verbose: logger.setLevel(logging.INFO)

    # load input image
    logger.info('Loading source image {}...'.format(args.input))
    try: 
        input_data = scipy.squeeze(load(args.input).get_data()).astype(scipy.bool_)
    except ImageFileError as e:
        logger.critical('The region image does not exist or its file type is unknown.')
        raise ArgumentError('The region image does not exist or its file type is unknown.', e)
    
    # iterate over designated dimension and create for each such extracted slice a text file
    logger.info('Processing per-slice and writing to files...')
    idx = [slice(None)] * input_data.ndim
    for slice_idx in range(input_data.shape[args.dimension]):
        idx[args.dimension] = slice(slice_idx, slice_idx + 1)
        # 2009: IM-0001-0027-icontour-manual
        file_name = '{}/IM-0001-{:04d}-{}contour-auto.txt'.format(args.target, slice_idx + args.offset, args.ctype)
        # 2012: P01-0080-icontour-manual.txt
        file_name = '{}/P{}-{:04d}-{}contour-auto.txt'.format(args.target, args.id, slice_idx + args.offset, args.ctype)
        
        # check if output file already exists
        if not args.force:
            if os.path.exists(file_name):
                logger.warning('The output file {} already exists. Skipping.'.format(file_name))
                continue
        
        # extract current slice
        image_slice = scipy.squeeze(input_data[idx])
        
        # remove all objects except the largest
        image_labeled, labels = scipy.ndimage.label(image_slice)
        if labels > 1:
            logger.info('The slice {} contains more than one object. Removing the smaller ones.'.format(file_name))
            # determine biggest
            biggest = 0
            biggest_size = 0
            for i in range(1, labels + 1):
                if len((image_labeled == i).nonzero()[0]) > biggest_size:
                    biggest_size = len((image_labeled == i).nonzero()[0])
                    biggest = i
            # remove others
            for i in range(1, labels + 1):
                if i == biggest: continue
                image_labeled[image_labeled == i] = 0
            # save to slice
            image_slice = image_labeled.astype(scipy.bool_)
        
        # perform some additional morphological operations
        image_slice = scipy.ndimage.morphology.binary_fill_holes(image_slice)
        footprint = scipy.ndimage.morphology.generate_binary_structure(image_slice.ndim, 3)
        image_slice = scipy.ndimage.morphology.binary_closing(image_slice, footprint, iterations=7)
        #image_slice = scipy.ndimage.morphology.binary_opening(image_slice, footprint, iterations=3)
        
        # if type == o, perform a dilation to increase the size slightly
        #if 'o' == args.ctype:
        #    footprint = scipy.ndimage.morphology.generate_binary_structure(image_slice.ndim, 3)
        #    image_slice = scipy.ndimage.morphology.binary_dilation(image_slice, iterations=3)
            
        # erode contour in slice
        input_eroded = scipy.ndimage.morphology.binary_erosion(image_slice, border_value=1)
        image_slice ^= input_eroded # xor
        
        # extract contour positions and put into right order
        contour_tmp = image_slice.nonzero()
        contour = [[] for i in range(len(contour_tmp[0]))]
        for i in range(len(contour_tmp[0])):
            for j in range(len(contour_tmp)):
                contour[i].append(contour_tmp[j][i]) # x, y, z, ....
                
        if 0 == len(contour):
            logger.warning('Empty contour for file {}. Skipping.'.format(file_name))
            continue
                
        # create final points following along the contour (incl. linear sub-voxel precision)
        divider = 2
        point = contour[0]
        point_pos = 0
        processed = [point_pos]
        contour_final = []
        while point:
            nearest_pos = __find_nearest(point, contour, processed)
            if False == nearest_pos: break
            contour_final.extend(__draw_line(point, contour[nearest_pos], divider))
            processed.append(nearest_pos)
            point = contour[nearest_pos]
        # make connection between last and first point
        contour_final.extend(__draw_line(point, contour[0], divider))
        
        # save contour to file
        logger.debug('Creating file {}...'.format(file_name))
        with open(file_name, 'w') as f:
            for line in contour_final:
                f.write('{}\n'.format(' '.join(map(str, line))))
                
    logger.info('Successfully terminated.')
    
def __draw_line(p1, p2, divider):
    """
    Returns divider points between the two supplied points, excluding p1 and including p2
    """
    delta_x = (p1[0] - p2[0]) / float(divider)
    delta_y = (p1[1] - p2[1]) / float(divider)
    points = []
    for i in range(1, divider + 1):
        points.append((p1[0] + delta_x * i,
                       p1[1] + delta_y * i))
    return points

def __find_nearest(point, contour, processed):
    """
    Returns the position of the point in contour nearest to the supplied point, excluding
    the once in processed.
    """
    nearest = False
    distance = 10000000
    for pos, p in enumerate(contour):
        if pos in processed: continue
        dist = __dist(point, p)
        if dist < distance:
            nearest = pos
            distance = dist
    if distance > math.sqrt(8): # do not allow distance more than 2 pixel diagonally; this avoids to include missed pixels in the end and to create artifacts
        return False
    return nearest
        
def __dist(p1, p2):
    """Returns the euclidean distance between two points."""
    return math.sqrt(math.pow(p1[0]- p2[0], 2) + math.pow(p1[1]- p2[1], 2))
    
def getArguments(parser):
    "Provides additional validation of the arguments collected by argparse."
    return parser.parse_args()

def getParser():
    "Creates and returns the argparse parser object."
    parser = argparse.ArgumentParser(description=__description__)
    
    parser.add_argument('input', help='The input binary image containing a single connected object.')
    parser.add_argument('dimension', type=int, help='The dimension over which to extract the per-slice contours.')
    parser.add_argument('ctype', help='The contour type. Can be i or o.')
    parser.add_argument('offset', type=int, help='The slice offset to rightly place the processed sub-volume.')
    parser.add_argument('id', help='The patient id (with a leading 0).')
    parser.add_argument('target', help='The target folder in which to store the generated files.')
    parser.add_argument('-f', dest='force', action='store_true', help='Set this flag to silently override files that exist.')
    parser.add_argument('-v', dest='verbose', action='store_true', help='Display more information.')
    parser.add_argument('-d', dest='debug', action='store_true', help='Display debug information.')
    
    return parser    

if __name__ == "__main__":
    main()
    