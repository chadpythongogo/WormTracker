import numpy as np
from scipy import interpolate
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle
import cv2
from skimage import morphology, graph
import h5py
from subprocess import check_output
import sys
import os
import wormimageprocessor as wp
import roitools
import time

# Interactive script - replace VideoReader with the Python/OpenCV approach
# (only need a single frame anyway)
# Automated analysis, parallelized per worm (16/video in the new ones):

# NOTE: Matlab crop indices are flipped (y,x,h,w) relative to Numpy arrays


libavPath = 'C:\\libav\\bin\\'


class WormVideo:
    imageProcessor = wp.WormImageProcessor()
    firstFrame = None
    pixelsPerMicron = None
    regions = []
    frameSize = None

    def __init__(self, videoFile, storeFile='temp.h5',
                 videoInfoStorePath='/video',
                 resultsStorePath='/worms',
                 numberOfRegions=16, allSameStrain=True,
                 referenceDistance=25000):
        self.videoFile = videoFile
        self.numberOfRegions = numberOfRegions
        self.allSameStrain = allSameStrain
        self.referenceDistance = referenceDistance
        self.storeFile = storeFile
        self.videoInfoStorePath = videoInfoStorePath
        self.resultsStorePath = resultsStorePath

    def readFirstFrame(self):
        video = cv2.VideoCapture()
        if video.open(self.videoFile):
            success, firstFrame = video.read()
            if not success:
                raise Exception("Couldn't read video")
            else:
                firstFrameChannels = cv2.split(firstFrame)
                self.firstFrame = firstFrameChannels[0]
                self.frameSize = self.firstFrame.shape
                self.nFrames = video.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT)
                print 'Video has ' + str(self.nFrames) + ' frames.'
                frameRate = video.get(cv2.cv.CV_CAP_PROP_FPS)
                print 'Video reports ' + str(frameRate) + ' fps.'
                self.imageProcessor.frameRate = \
                    float(raw_input('Enter correct frame rate:'))

        else:
            raise Exception("Couldn't open video")

    def defineRegions(self):
        if self.firstFrame is None:
            self.readFirstFrame()

        # show first frame and ask user to select regions
        if self.allSameStrain:
            strain = raw_input("Enter the strain name:")
        regions = []

        def drawAllRegions():
            plt.imshow(self.firstFrame, cmap=plt.gray())
            ax = plt.gca()
            for region in regions:
                # draw region box
                rect = Rectangle((region[0][0], region[0][1]), region[0][2],
                                 region[0][3], color='k', fill=False)
                ax.add_patch(rect)
                # label region in lower left corner
                plt.text(region[0][0]+5, region[0][1]+region[0][3],
                         region[1] + ' ' + region[2])

        for i in xrange(self.numberOfRegions):
            raw_input("Select region " + str(i) + " on the figure...")
            drawAllRegions()  # show all regions already picked
            sel = roitools.RectangleRegionSelector()  # track selection
            plt.show()  # request user to select region on figure
            if not self.allSameStrain:
                strain = raw_input("Enter the strain name: ")
            wormName = raw_input("Enter the worm ID " +
                                 "(press enter to use the region number): ")
            if wormName is "":
                wormName = str(i+1)
            regions.append((sel.asXYWH(), strain, wormName))
        # show all picked regions
        drawAllRegions()
        plt.show()

        self.regions = []  # remove old regions, if any
        # add regions
        for region in regions:
            self.addRegion(tuple([int(round(x)) for x in region[0]]),
                           region[1], region[2])

    def addRegion(self, regionBounds, strain, name):
        """Adds the video region containing one worm.

        regionBounds: (x,y,w,h)
        strain: The strain name
        name: The worm identifier
        """
        wr = WormVideoRegion(self.videoFile, self.imageProcessor,
                             self.storeFile,
                             regionBounds, self.pixelsPerMicron,
                             resultsStorePath=self.resultsStorePath,
                             strainName=strain,
                             wormName=name)
        self.regions.append(wr)

    def determinePixelSize(self):
        if self.firstFrame is None:
            self.readFirstFrame()
        raw_input("Draw a " + str(self.referenceDistance) +
                  " um line on the figure...")
        plt.imshow(self.firstFrame, cmap=plt.gray())
        sel = roitools.LineRegionSelector()
        plt.show()
        self.imageProcessor.pixelSize = (sel.distance() /
                                         self.referenceDistance)
        self.imageProcessor.determineNumberOfPosturePoints()
        print ("The pixel size is " + str(1.0/self.imageProcessor.pixelSize) +
               " um/px.")

    def defineFoodRegions(self):
        if self.firstFrame is None:
            self.readFirstFrame()
        raw_input("Draw a circle covering the food for each region...")
        for region in self.regions:
            crop = region.cropRegion
            plt.imshow(wp.cropImageToRegion(self.firstFrame, crop),
                       plt.gray())
            plt.title(region.strainName + " " + region.wormName)
            sel = roitools.CircleRegionSelector()
            plt.show()
            region.foodCircle = sel.asXYR()

    def testBackgroundFilter(self):
        if self.firstFrame is None:
            self.readFirstFrame()
        ax1 = plt.subplot(1, 2, 1)
        plt.imshow(self.firstFrame, cmap=plt.gray())
        plt.title('Original Frame')
        plt.subplot(1, 2, 2, sharex=ax1, sharey=ax1)
        plt.imshow(self.imageProcessor.applyBackgroundFilter(self.firstFrame),
                   cmap=plt.gray())
        plt.title('Background Filtered')
        plt.show()

    def testThreshold(self):
        if self.firstFrame is None:
            self.readFirstFrame()
        ax1 = plt.subplot(1, 2, 1)
        filtered = self.imageProcessor.applyBackgroundFilter(self.firstFrame)
        plt.imshow(filtered, cmap=plt.gray())
        plt.title('Background Filtered Frame')
        plt.subplot(1, 2, 2, sharex=ax1, sharey=ax1)
        plt.imshow(self.imageProcessor.applyThreshold(filtered),
                   cmap=plt.gray())
        plt.title('Thresholded')
        plt.show()

    def testWormIdentification(self):
        plt.figure()
        for i, region in enumerate(self.regions):
            plt.subplot(3, np.ceil(np.float64(self.numberOfRegions)/3.0), i+1)
            ip = self.imageProcessor
            cropped = wp.cropImageToRegion(self.firstFrame, region.cropRegion)
            filtered = ip.applyBackgroundFilter(cropped)
            thresholded = ip.applyThreshold(filtered)
            cleaned = ip.applyMorphologicalCleaning(thresholded)
            possibleWorms = ip.identifyPossibleWorms(cleaned)
            likelyWorm = max(possibleWorms, key=lambda worm: worm[1])
            if likelyWorm is not None:
                wormImage = WormImage(region, filtered, thresholded,
                                      likelyWorm[0])
                wormImage.measureWorm()
                wormImage.plot()
            plt.title(region.strainName + ' ' + region.wormName)
        plt.show()

    def saveConfiguration(self):
        if os.path.isfile(self.storeFile):
            mode = 'r+'
        else:
            mode = 'w'
        with h5py.File(self.storeFile, mode) as f:
            pre = self.videoInfoStorePath
            # check whether datasets exist
            if pre not in f:
                f.create_group(pre)
            g = f[pre]
            if 'videoFile' not in g:
                dt = h5py.special_dtype(vlen=str)
                g.create_dataset('videoFile', (1,), dtype=dt)

            # write configuration
            # strip directory info from file
            path, fileName = os.path.split(self.videoFile)
            g['videoFile'][...] = fileName
            # save imaging configuration
            self.imageProcessor.saveConfiguration(self.storeFile,
                                                  self.videoInfoStorePath)
            # save information for each region
            for region in self.regions:
                region.saveConfiguration()

    def processRegions(self):
        self.saveConfiguration()
        print 'Processing regions of video...'
        for i, region in enumerate(self.regions):
            print 'Processing region ' + str(i) + ' of ' + str(len(self.regions))
            tStart = time.clock()
            region.process()
            tStop = time.clock()
            tDuration = (tStop - tStart) / 60.0
            print 'Analysis of region took ' + str(tDuration) + ' min.'

    def processRegionsParallel(self):
        raise NotImplemented()


class WormVideoRegion:
    """ Processes a region of a worm behavior experiment containing
        a single worm. """
    frameRate = 11.5
    frameSize = (2736, 2192)
    foodCircle = None

    croppedFilteredVideoFile = None
    thresholdedVideoFile = None

    def __init__(self, videoFile, imageProcessor, resultsStoreFile,
                 cropRegion, pixelSize,
                 resultsStorePath='/worms', outputPrefix=None,
                 strainName='Unknown', wormName=''):
        self.videoFile = videoFile
        self.imageProcessor = imageProcessor
        self.resultsStoreFile = resultsStoreFile
        self.resultsStorePath = resultsStorePath
        self.cropRegion = cropRegion
        self.pixelSize = pixelSize
        self.strainName = strainName
        self.wormName = wormName
        if outputPrefix is None:
            outputPrefix = self.strainName + '_' + self.wormName + '_'
        self.outputPrefix = outputPrefix

    def process(self):
        """ Processes the video region. """
        self.generateCroppedFilteredVideo()
        self.generateThresholdedVideo()
        self.identifyWorm()

    def generateCroppedFilteredVideo(self):
        """ Crops and filters the video frames """
        if self.croppedFilteredVideoFile is None:
            self.croppedFilteredVideoFile = self.outputPrefix + 'cropped.avi'

        print (self.strainName + ' ' + self.wormName +
               ": Generating cropped video using libav...")
        tStart = time.clock()
        check_output([libavPath + 'avconv', '-i', self.videoFile, '-vf',
                      'crop=' + self._cropRegionForAvconv(), '-c:v',
                      'rawvideo', '-pix_fmt', 'yuv420p',
                      '-y', 'temp_' + self.croppedFilteredVideoFile])
        tEndCrop = time.clock()
        print (self.strainName + ' ' + self.wormName +
               ": Cropping took " + str(tEndCrop-tStart) + ' s.')

        print (self.strainName + ' ' + self.wormName +
               ": Bottom hat filtering frames...")
        tStartFilter = time.clock()
        croppedVideo = cv2.VideoCapture()
        if croppedVideo.open('temp_' + self.croppedFilteredVideoFile):
            filteredVideoOut = cv2.VideoWriter()
            if filteredVideoOut.open(self.croppedFilteredVideoFile,
                                     cv2.cv.CV_FOURCC('Y', '8', '0',
                                                      '0'),
                                     self.frameRate,
                                     (self.cropRegion[2],
                                      self.cropRegion[3]),
                                     isColor=False):
                # loop through video frames
                success, frame = croppedVideo.read()
                while success:
                    framev = cv2.split(frame)  # split the channels
                    # filter frame: inverted black hat filter
                    filtered = \
                        self.imageProcessor.applyBackgroundFilter(framev[0])
                    # write frame to output
                    filteredVideoOut.write(filtered)
                    # read next video frame
                    success, frame = croppedVideo.read()
            else:
                raise Exception('Error opening filtered video for ' +
                                'writing in OpenCV.')
        else:
            raise Exception('Error opening filtered video in OpenCV.')
        tEndFilter = time.clock()
        print (self.strainName + ' ' + self.wormName +
               ": Filtering took " + str(tEndFilter-tStartFilter) + ' s.')
        # TODO: Delete temporary cropped video

    def _cropRegionForAvconv(self):
        return (str(self.cropRegion[2]) + ':' +
                str(self.cropRegion[3]) + ':' +
                str(self.cropRegion[0]) + ':' +
                str(self.cropRegion[1]) + ':')

    def generateThresholdedVideo(self):
        """ Thresholds all the filtered frames and applies
        morphological cleaning steps
        """
        if self.thresholdedVideoFile is None:
            self.thresholdedVideoFile = self.outputPrefix + 'thresholded.avi'

        print (self.strainName + ' ' + self.wormName +
               ": Thresholding and cleaning video frames...")
        tStart = time.clock()
        filteredVideo = cv2.VideoCapture()
        if filteredVideo.open(self.croppedFilteredVideoFile):
            thresholdedVideoOut = cv2.VideoWriter()
            if thresholdedVideoOut.open(self.thresholdedVideoFile,
                                        cv2.cv.CV_FOURCC('Y', '8',
                                                         '0', '0'),
                                        self.frameRate,
                                        (self.cropRegion[2],
                                         self.cropRegion[3]),
                                        isColor=False):
                # loop through video frames
                success, frame = filteredVideo.read()
                while success:
                    framev = cv2.split(frame)  # split the channels
                    ip = self.imageProcessor
                    thresholded = ip.applyThreshold(framev[0])
                    cleaned = ip.applyMorphologicalCleaning(thresholded)
                    # write frame to output
                    thresholdedVideoOut.write(np.uint8(cleaned)*255)
                    # read next video frame
                    success, frame = filteredVideo.read()
            else:
                raise Exception('Error opening filtered video for ' +
                                'writing in OpenCV.')
        else:
            raise Exception('Error opening filtered video in OpenCV.')
        tStop = time.clock()
        print (self.strainName + ' ' + self.wormName +
               ": Thresholding and cleaning took " + str(tStop-tStart) + ' s.')
        # TODO: call('avconv','-i',self.croppedFilteredVideoFile,'-vf','?')
        # to figure out how to do this

    def identifyWorm(self):
        """ Loops through thresholded frames, identifies the likely worm,
            measures its properties, and stores the result in the data store
        """
        print (self.strainName + ' ' + self.wormName +
               ": Identifying worm in each frame...")
        try:
            bwVideo = cv2.VideoCapture()
            if bwVideo.open(self.thresholdedVideoFile):
                nFrames = bwVideo.get(cv2.cv.CV_CAP_PROP_FRAME_COUNT)
                grayVideo = cv2.VideoCapture()
                if grayVideo.open(self.croppedFilteredVideoFile):
                    # loop through video frames
                    count = 0
                    # read filtered video frame
                    bwSuccess, grayFrame = grayVideo.read()
                    # read thresholded video frame
                    graySuccess, bwFrame = bwVideo.read()
                    while bwSuccess and graySuccess:
                        tStart = time.clock()
                        print (self.strainName + ' ' + self.wormName +
                               ": Identifying worm in frame " + str(count+1) +
                               ' of ' + str(nFrames))
                        # split the channels
                        bwFramev = cv2.split(bwFrame)
                        grayFramev = cv2.split(grayFrame)

                        ip = self.imageProcessor
                        # identify possible worms in image
                        # returns contours, areas
                        possibleWorms = ip.identifyPossibleWorms(bwFramev[0])
                        if (possibleWorms is not None and
                            len(possibleWorms) > 0):
                            # likely worm is the largest area
                            likelyWorm = max(possibleWorms,
                                             key=lambda worm: worm[1])
                        else:
                            likelyWorm = None

                        if likelyWorm is not None:
                            # Create worm object which will measure
                            # the properties of the worm
                            worm = self.measureWorm(grayFramev[0],
                                                    np.equal(bwFramev[0], 1),
                                                    likelyWorm[0])

                            # write results to HDF5 store
                            pre = (self.resultsStorePath + '/' +
                                   self.strainName + '/' +
                                   self.wormName)
                            worm.store(self.resultsStoreFile,
                                       pre, count)

                        count += 1  # increment frame counter

                        # read next video frame
                        bwSuccess, grayFrame = grayVideo.read()
                        graySuccess, bwFrame = bwVideo.read()
                        tEnd = time.clock()
                        tRemainEst = (np.float64(nFrames - count)*(tEnd-tStart)
                                      / 60.0)
                        print (self.strainName + ' ' + self.wormName +
                               ": Expected to finish in " + str(tRemainEst) +
                               ' min.')
                else:
                    raise Exception('Error opening filtered video ' +
                                    'in OpenCV.')
            else:
                raise Exception('Error opening thresholded video in ' +
                                'OpenCV.')
        except IOError as e:
            print "I/O error({0}): {1}".format(e.errno, e.strerror)
        except:
            print "Unexpected error:", sys.exc_info()[0]
            raise

    def measureWorm(self, grayFrame, bwFrame, wormContour):
        worm = WormImage(self, grayFrame, bwFrame, wormContour)
        worm.measureWorm()
        return worm

    def saveConfiguration(self):
        if os.path.isfile(self.resultsStoreFile):
            mode = 'r+'
        else:
            mode = 'w'
        with h5py.File(self.resultsStoreFile, mode) as f:
            pre = (self.resultsStorePath + '/' +
                   self.strainName + '/' +
                   str(self.wormName))
            # check whether datasets exist
            if pre not in f:
                f.create_group(pre)
            g = f[pre]
            if 'cropRegion' not in g:
                g.create_dataset('cropRegion', (4,), dtype='int32')
                g.create_dataset('foodCircle', (3,), dtype='float64')

            # write configuration
            g['cropRegion'][...] = self.cropRegion
            g['foodCircle'][...] = self.foodCircle


class WormImage:
    # default plot variables
    smoothing = 0.05
    outlineColor = (255, 255, 0)
    skeletonColor = 'y'
    postureColormap = plt.get_cmap('PuOr')
    centroidColor = 'r'
    midpointColor = 'r'

    # image data and measurements
    boundingBox = None
    bwWormImage = None
    grayWormImage = None
    outlinedWormImage = None
    skeletonizedWormImage = None
    skeleton = None
    skeletonSpline = None
    centroid = None
    midpoint = None
    width = None
    length = None
    posture = None
    meanBodyAngle = None

    def __init__(self, videoRegion, grayFrame, bwFrame, wormContour):
        self.videoRegion = videoRegion
        self.grayFrame = grayFrame
        self.bwFrame = bwFrame
        self.wormContour = wormContour

    def cropToWorm(self):
        """ crop filtered and thresholded frames to worm """
        # measure bounding box
        self.boundingBox = cv2.boundingRect(self.wormContour)  # x,y,w,h

        # crop frame
        self.bwWormImage = self.bwFrame[
            self.boundingBox[1]:self.boundingBox[1]+self.boundingBox[3],
            self.boundingBox[0]:self.boundingBox[0]+self.boundingBox[2]]
        self.grayWormImage = self.grayFrame[
            self.boundingBox[1]:self.boundingBox[1]+self.boundingBox[3],
            self.boundingBox[0]:self.boundingBox[0]+self.boundingBox[2]]

    def outlineWorm(self):
        self.outlinedWormImage = np.zeros(self.bwWormImage.shape,
                                          dtype=np.uint8)
        cv2.drawContours(self.outlinedWormImage,
                         [self.toCroppedCoordinates(self.wormContour)],
                         0, 255, thickness=1)
        self.outlinedWormImage = np.equal(self.outlinedWormImage, 255)

    def skeletonizeWorm(self):
        self.skeletonizedWormImage = morphology.skeletonize(self.bwWormImage)
        skeletonEnds = wp.find1Cpixels(self.skeletonizedWormImage)
        skeletonEndPts = cv2.findNonZero(np.uint8(skeletonEnds))
        if skeletonEndPts is None:
            skeletonEndPts = []
        nEndPts = len(skeletonEndPts)
        if nEndPts < 2:  # skeleton is a cirle (Omega turn)
            self.badSkeletonization = True
            self.crossedWorm = True
        elif nEndPts > 2:  # skeleton has spurs
            self.badSkeletonization = True
        else:
            skeletonInverted = np.logical_not(self.skeletonizedWormImage)
            skeletonPts, cost = \
                graph.route_through_array(np.uint8(skeletonInverted),
                                          np.flipud(skeletonEndPts[0][0]),
                                          np.flipud(skeletonEndPts[1][0]),
                                          geometric=True)
            self.skeleton = np.array([[pt[0], pt[1]] for pt in skeletonPts])
            self.badSkeletonization = False

    def measureWorm(self):
        # make sure the frame has been cropped
        if self.bwWormImage is None or self.grayWormImage is None:
            self.cropToWorm()  # crop the frame to the worm

        self.calculateCentroid()  # measure centroid
        self.calculatePosture()  # measure length, midpoint, and body angles
        self.calculateWidth()  # measure width

    def calculateCentroid(self):
        moments = cv2.moments(self.wormContour)
        if moments['m00'] != 0:  # only calculate if there is a non-zero area
            cx = int(moments['m10']/moments['m00'])  # cx = M10/M00
            cy = int(moments['m01']/moments['m00'])
            self.centroid = np.flipud(self.toCroppedCoordinates([cx, cy]))
        else:
            self.centroid = None

    def calculateWidth(self):
        if self.badSkeletonization:
            return
        # approximate width as 2*shortest path to contour at midpoint
        mp = np.flipud(self.midpoint)
        self.outlineWorm()
        cpts = np.float64(cv2.findNonZero(np.uint8(self.outlinedWormImage)))
        self.width = (min(np.sqrt(np.sum(np.float64(cpts - mp)**2, axis=2)))
                      * 2.0 / self.videoRegion.imageProcessor.pixelSize)

    def calculatePosture(self):
        self.skeletonizeWorm()  # find skeleton and length
        if self.badSkeletonization:
            self.skeleton = np.zeros((0, 2))
            self.skeletonSpline = np.zeros((0, 2))
            self.posture = np.zeros((0,))
            return
        pts = np.float64(self.skeleton)
        # distance along skeleton
        s = np.zeros((pts.shape[0], 1))
        for i in xrange(1, len(s)):
            s[i] = (np.sqrt((pts[i, 0]-pts[i-1, 0])**2 +
                            (pts[i, 1]-pts[i-1, 1])**2) +
                    s[i-1])
        # calculate length
        self.length = s[-1]/self.videoRegion.imageProcessor.pixelSize
        # fit spline to skeleton
        fx = interpolate.UnivariateSpline(s/s[-1], pts[:, 0],
                                          s=self.smoothing*pts.shape[0])
        fy = interpolate.UnivariateSpline(s/s[-1], pts[:, 1],
                                          s=self.smoothing*pts.shape[0])
        # find midpoint
        self.midpoint = (fx(0.5), fy(0.5))
        # calculate body angles
        nAngles = self.videoRegion.imageProcessor.numberOfPosturePoints
        theta = np.zeros(nAngles)
        sp = np.linspace(0, 1, nAngles+2)
        spi = np.array([fx(sp), fy(sp)]).transpose()
        self.skeletonSpline = spi
        for i in xrange(1, nAngles+1):
            theta[i-1] = np.arctan2((spi[i+1, 1]-spi[i-1, 1])/2.0,
                                    (spi[i+1, 0]-spi[i-1, 0])/2.0)
        theta = np.unwrap(theta)
        self.meanBodyAngle = np.mean(theta)
        self.posture = theta - self.meanBodyAngle

    def toCroppedCoordinates(self, pts):
        if self.boundingBox is None:
            self.cropToWorm()
        return pts - np.array(self.boundingBox[0:2])

    def toRegionCoordinates(self, pts):
        if self.boundingBox is None:
            self.cropToWorm()  # crop the frame to the worm
        return pts + np.array(self.boundingBox[0:2])

    def store(self, storeFile, storePath, index):
        if os.path.isfile(storeFile):
            mode = 'r+'
        else:
            mode = 'w'
        with h5py.File(storeFile, mode) as f:
            pre = storePath + '/' + str(index)
            # check whether datasets exist
            f.require_group(pre)
            g = f[pre]
            g.require_dataset('boundingBox', (4,), dtype='int32')
            g.require_dataset('bwWormImage', self.bwWormImage.shape,
                              maxshape=self.videoRegion.frameSize,
                              chunks=True,
                              compression='gzip', dtype='b')
            g.require_dataset('grayWormImage', self.grayWormImage.shape,
                              maxshape=self.videoRegion.frameSize,
                              chunks=True,
                              compression='gzip', dtype='uint8')
            g.require_dataset('skeleton', self.skeleton.shape,
                              maxshape=(200, 2),
                              chunks=True, dtype='int32')
            g.require_dataset('skeletonSpline', self.skeletonSpline.shape,
                              maxshape=(100, 2),
                              chunks=True, dtype='float64')
            g.require_dataset('centroid', (2,), dtype='float64')
            g.require_dataset('midpoint', (2,), dtype='float64')
            g.require_dataset('width', (1,), dtype='float64')
            g.require_dataset('length', (1,), dtype='float64')
            g.require_dataset('meanBodyAngle', (1,), dtype='float64')
            g.require_dataset('posture', self.posture.shape,
                              maxshape=(100,), dtype='float64')
            g.require_dataset('wormContour', self.wormContour.shape,
                              maxshape=(None, 1, 2), chunks=True,
                              dtype='int32')
            g.require_dataset('time', (1,), dtype='float64')
            # write configuration
            g['boundingBox'][...] = np.array(self.boundingBox)
            g['bwWormImage'][...] = self.bwWormImage
            g['grayWormImage'][...] = self.grayWormImage
            g['wormContour'][...] = self.wormContour
            rate = self.videoRegion.imageProcessor.frameRate
            g['time'][...] = np.float64(index)/rate
            g['centroid'][...] = self.centroid
            if not self.badSkeletonization:
                g['skeleton'][...] = self.skeleton
                g['skeletonSpline'][...] = self.skeletonSpline
                g['midpoint'][...] = self.midpoint
                g['width'][...] = self.width
                g['length'][...] = self.length
                g['meanBodyAngle'][...] = self.meanBodyAngle
                g['posture'][...] = self.posture

    def plot(self):
        if self.bwWormImage is None:
            self.cropToWorm()
        if self.centroid is None:
            self.measureWorm()
        im = cv2.cvtColor(cv2.normalize(self.grayWormImage,
                                        alpha=0,
                                        beta=255,
                                        norm_type=cv2.NORM_MINMAX),
                          cv2.COLOR_GRAY2RGB)
        cv2.drawContours(im,
                         [self.toCroppedCoordinates(self.wormContour)],
                         0, self.outlineColor)
        plt.imshow(im)
        plt.hold(True)
        plt.plot(self.skeleton[:, 1], self.skeleton[:, 0], '-',
                 color=self.skeletonColor)
        plt.scatter(self.skeletonSpline[1:-1, 1], self.skeletonSpline[1:-1, 0],
                    c=self.posture, cmap=self.postureColormap, s=100)
        plt.plot(self.centroid[1], self.centroid[0], 'o', ms=12,
                 color=self.centroidColor)
        plt.plot(self.midpoint[1], self.midpoint[0], 's', ms=12,
                 color=self.midpointColor)