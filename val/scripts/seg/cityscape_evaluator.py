#!/usr/bin/env python
#-*- coding:utf-8 -*-
# Author: Donny You(donnyyou@163.com)
# Evaluation of cityscape.


from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import fnmatch
import argparse
import platform
import sys

try:
    from itertools import izip
except ImportError:
    izip = zip

# Cityscapes imports
from val.scripts.seg.cityscape.evaluation.csHelpers import *

# C Support
# Enable the cython support for faster evaluation, this is necessary for speeding up your model results
# Only tested for Ubuntu 64bit OS
CSUPPORT = True
# Check if C-Support is available for better performance
if CSUPPORT:
    try:
        import val.scripts.seg.cityscape.evaluation.addToConfusionMatrix as addToConfusionMatrix
    except:
        CSUPPORT = False


# A class to collect all bunch of data
class CArgs(object):
    def __init__(self, data_path=None, out_path=None, predict_path=None):
        # Where to look for Cityscapes, note that data path is equal to gt path
        if 'CITYSCAPES_DATASET' in os.environ:
            self.cityscapesPath = os.environ['CITYSCAPES_DATASET']
        else:
            self.cityscapesPath = os.path.join(data_path)

        if 'CITYSCAPES_EXPORT_DIR' in os.environ:
            export_dir = os.environ['CITYSCAPES_EXPORT_DIR']
            if not os.path.isdir(export_dir):
                raise ValueError("CITYSCAPES_EXPORT_DIR {} is not a directory".format(export_dir))
            self.exportFile = "{}/resultPixelLevelSemanticLabeling.json".format(export_dir)
        else:
            self.exportFile = os.path.join(out_path, "evaluationResults", "resultPixelLevelSemanticLabeling.json")
        # Parameters that should be modified by user
        self.groundTruthSearch  = os.path.join( self.cityscapesPath, "*", "*_gtFine_labelIds.png" )

        # Remaining params
        self.evalInstLevelScore = True
        self.evalPixelAccuracy  = False
        self.evalLabels         = []
        self.printRow           = 5
        self.normalized         = True
        self.colorized          = hasattr(sys.stderr, "isatty") and sys.stderr.isatty() and platform.system()=='Linux'
        self.bold               = colors.BOLD if self.colorized else ""
        self.nocol              = colors.ENDC if self.colorized else ""
        self.JSONOutput         = True
        self.quiet              = False

        self.avgClassSize       = {
        "bicycle"    :  4672.3249222261 ,
        "caravan"    : 36771.8241758242 ,
        "motorcycle" :  6298.7200839748 ,
        "rider"      :  3930.4788056518 ,
        "bus"        : 35732.1511111111 ,
        "train"      : 67583.7075812274 ,
        "car"        : 12794.0202738185 ,
        "person"     :  3462.4756337644 ,
        "truck"      : 27855.1264367816 ,
        "trailer"    : 16926.9763313609 ,
    }

        # store some parameters for finding predictions in the args variable
        # the values are filled when the method getPrediction is first called
        self.predictionPath = predict_path
        self.predictionWalk = None


## method part
def getPrediction( args, groundTruthFile ):
    # determine the prediction path, if the method is first called
    if not args.predictionPath:
        rootPath = None
        if 'CITYSCAPES_RESULTS' in os.environ:
            rootPath = os.environ['CITYSCAPES_RESULTS']
        elif 'CITYSCAPES_DATASET' in os.environ:
            rootPath = os.path.join( os.environ['CITYSCAPES_DATASET'] , "results" )
        else:
            rootPath = os.path.join(os.path.dirname(os.path.realpath(__file__)),'..','..','results')

        if not os.path.isdir(rootPath):
            printError("Could not find a result root folder. Please read the instructions of this method.")

        args.predictionPath = rootPath

    # walk the prediction path, if not happened yet
    if not args.predictionWalk:
        walk = []
        for root, dirnames, filenames in os.walk(args.predictionPath):
            walk.append( (root,filenames) )
        args.predictionWalk = walk

    csFile = getCsFileInfo(groundTruthFile)
    filePattern = "{}_{}_{}*.png".format( csFile.city , csFile.sequenceNb , csFile.frameNb )

    predictionFile = None
    for root, filenames in args.predictionWalk:
        for filename in fnmatch.filter(filenames, filePattern):
            if not predictionFile:
                predictionFile = os.path.join(root, filename)
            else:
                printError("Found multiple predictions for ground truth {}".format(groundTruthFile))

    if not predictionFile:
        printError("Found no prediction for ground truth {}".format(groundTruthFile))

    return predictionFile

# Generate empty confusion matrix and create list of relevant labels
def generateMatrix(args):
    args.evalLabels = []
    for label in labels:
        if (label.id < 0):
            continue
        # we append all found labels, regardless of being ignored
        args.evalLabels.append(label.id)
    maxId = max(args.evalLabels)
    # We use longlong type to be sure that there are no overflows
    return np.zeros(shape=(maxId + 1, maxId + 1), dtype=np.ulonglong)


def generateInstanceStats(args):
    instanceStats = {}
    instanceStats["classes"] = {}
    instanceStats["categories"] = {}
    for label in labels:
        if label.hasInstances and not label.ignoreInEval:
            instanceStats["classes"][label.name] = {}
            instanceStats["classes"][label.name]["tp"] = 0.0
            instanceStats["classes"][label.name]["tpWeighted"] = 0.0
            instanceStats["classes"][label.name]["fn"] = 0.0
            instanceStats["classes"][label.name]["fnWeighted"] = 0.0
    for category in category2labels:
        labelIds = []
        allInstances = True
        for label in category2labels[category]:
            if label.id < 0:
                continue
            if not label.hasInstances:
                allInstances = False
                break
            labelIds.append(label.id)
        if not allInstances:
            continue

        instanceStats["categories"][category] = {}
        instanceStats["categories"][category]["tp"] = 0.0
        instanceStats["categories"][category]["tpWeighted"] = 0.0
        instanceStats["categories"][category]["fn"] = 0.0
        instanceStats["categories"][category]["fnWeighted"] = 0.0
        instanceStats["categories"][category]["labelIds"] = labelIds

    return instanceStats


# Get absolute or normalized value from field in confusion matrix.
def getMatrixFieldValue(confMatrix, i, j, args):
    if args.normalized:
        rowSum = confMatrix[i].sum()
        if (rowSum == 0):
            return float('nan')
        return float(confMatrix[i][j]) / rowSum
    else:
        return confMatrix[i][j]


# Calculate and return IOU score for a particular label
def getIouScoreForLabel(label, confMatrix, args):
    if id2label[label].ignoreInEval:
        return float('nan')

    # the number of true positive pixels for this label
    # the entry on the diagonal of the confusion matrix
    tp = np.longlong(confMatrix[label, label])

    # the number of false negative pixels for this label
    # the row sum of the matching row in the confusion matrix
    # minus the diagonal entry
    fn = np.longlong(confMatrix[label, :].sum()) - tp

    # the number of false positive pixels for this labels
    # Only pixels that are not on a pixel with ground truth label that is ignored
    # The column sum of the corresponding column in the confusion matrix
    # without the ignored rows and without the actual label of interest
    notIgnored = [l for l in args.evalLabels if not id2label[l].ignoreInEval and not l == label]
    fp = np.longlong(confMatrix[notIgnored, label].sum())

    # the denominator of the IOU score
    denom = (tp + fp + fn)
    if denom == 0:
        return float('nan')

    # return IOU
    return float(tp) / denom


# Calculate and return IOU score for a particular label
def getInstanceIouScoreForLabel(label, confMatrix, instStats, args):
    if id2label[label].ignoreInEval:
        return float('nan')

    labelName = id2label[label].name
    if not labelName in instStats["classes"]:
        return float('nan')

    tp = instStats["classes"][labelName]["tpWeighted"]
    fn = instStats["classes"][labelName]["fnWeighted"]
    # false postives computed as above
    notIgnored = [l for l in args.evalLabels if not id2label[l].ignoreInEval and not l == label]
    fp = np.longlong(confMatrix[notIgnored, label].sum())

    # the denominator of the IOU score
    denom = (tp + fp + fn)
    if denom == 0:
        return float('nan')

    # return IOU
    return float(tp) / denom


# Calculate prior for a particular class id.
def getPrior(label, confMatrix):
    return float(confMatrix[label, :].sum()) / confMatrix.sum()


# Get average of scores.
# Only computes the average over valid entries.
def getScoreAverage(scoreList, args):
    validScores = 0
    scoreSum = 0.0
    for score in scoreList:
        if not math.isnan(scoreList[score]):
            validScores += 1
            scoreSum += scoreList[score]
    if validScores == 0:
        return float('nan')
    return scoreSum / validScores


# Calculate and return IOU score for a particular category
def getIouScoreForCategory(category, confMatrix, args):
    # All labels in this category
    labels = category2labels[category]
    # The IDs of all valid labels in this category
    labelIds = [label.id for label in labels if not label.ignoreInEval and label.id in args.evalLabels]
    # If there are no valid labels, then return NaN
    if not labelIds:
        return float('nan')

    # the number of true positive pixels for this category
    # this is the sum of all entries in the confusion matrix
    # where row and column belong to a label ID of this category
    tp = np.longlong(confMatrix[labelIds, :][:, labelIds].sum())

    # the number of false negative pixels for this category
    # that is the sum of all rows of labels within this category
    # minus the number of true positive pixels
    fn = np.longlong(confMatrix[labelIds, :].sum()) - tp

    # the number of false positive pixels for this category
    # we count the column sum of all labels within this category
    # while skipping the rows of ignored labels and of labels within this category
    notIgnoredAndNotInCategory = [l for l in args.evalLabels if
                                  not id2label[l].ignoreInEval and id2label[l].category != category]
    fp = np.longlong(confMatrix[notIgnoredAndNotInCategory, :][:, labelIds].sum())

    # the denominator of the IOU score
    denom = (tp + fp + fn)
    if denom == 0:
        return float('nan')

    # return IOU
    return float(tp) / denom


# Calculate and return IOU score for a particular category
def getInstanceIouScoreForCategory(category, confMatrix, instStats, args):
    if not category in instStats["categories"]:
        return float('nan')
    labelIds = instStats["categories"][category]["labelIds"]

    tp = instStats["categories"][category]["tpWeighted"]
    fn = instStats["categories"][category]["fnWeighted"]

    # the number of false positive pixels for this category
    # same as above
    notIgnoredAndNotInCategory = [l for l in args.evalLabels if
                                  not id2label[l].ignoreInEval and id2label[l].category != category]
    fp = np.longlong(confMatrix[notIgnoredAndNotInCategory, :][:, labelIds].sum())

    # the denominator of the IOU score
    denom = (tp + fp + fn)
    if denom == 0:
        return float('nan')

    # return IOU
    return float(tp) / denom


# create a dictionary containing all relevant results
def createResultDict(confMatrix, classScores, classInstScores, categoryScores, categoryInstScores,
                     perImageStats, args):
    # write JSON result file
    wholeData = {}
    wholeData["confMatrix"] = confMatrix.tolist()
    wholeData["priors"] = {}
    wholeData["labels"] = {}
    for label in args.evalLabels:
        wholeData["priors"][id2label[label].name] = getPrior(label, confMatrix)
        wholeData["labels"][id2label[label].name] = label
    wholeData["classScores"] = classScores
    wholeData["classInstScores"] = classInstScores
    wholeData["categoryScores"] = categoryScores
    wholeData["categoryInstScores"] = categoryInstScores
    wholeData["averageScoreClasses"] = getScoreAverage(classScores, args)
    wholeData["averageScoreInstClasses"] = getScoreAverage(classInstScores, args)
    wholeData["averageScoreCategories"] = getScoreAverage(categoryScores, args)
    wholeData["averageScoreInstCategories"] = getScoreAverage(categoryInstScores, args)

    if perImageStats:
        wholeData["perImageScores"] = perImageStats

    return wholeData


def writeJSONFile(wholeData, args):
    path = os.path.dirname(args.exportFile)
    ensurePath(path)
    writeDict2JSON(wholeData, args.exportFile)


# Print confusion matrix
def printConfMatrix(confMatrix, args):
    # print line
    print("\b{text:{fill}>{width}}".format(width=15, fill='-', text=" "), end=' ')
    for label in args.evalLabels:
        print("\b{text:{fill}>{width}}".format(width=args.printRow + 2, fill='-', text=" "), end=' ')
    print("\b{text:{fill}>{width}}".format(width=args.printRow + 3, fill='-', text=" "))

    # print label names
    print("\b{text:>{width}} |".format(width=13, text=""), end=' ')
    for label in args.evalLabels:
        print("\b{text:^{width}} |".format(width=args.printRow, text=id2label[label].name[0]), end=' ')
    print("\b{text:>{width}} |".format(width=6, text="Prior"))

    # print line
    print("\b{text:{fill}>{width}}".format(width=15, fill='-', text=" "), end=' ')
    for label in args.evalLabels:
        print("\b{text:{fill}>{width}}".format(width=args.printRow + 2, fill='-', text=" "), end=' ')
    print("\b{text:{fill}>{width}}".format(width=args.printRow + 3, fill='-', text=" "))

    # print matrix
    for x in range(0, confMatrix.shape[0]):
        if (not x in args.evalLabels):
            continue
        # get prior of this label
        prior = getPrior(x, confMatrix)
        # skip if label does not exist in ground truth
        if prior < 1e-9:
            continue

        # print name
        name = id2label[x].name
        if len(name) > 13:
            name = name[:13]
        print("\b{text:>{width}} |".format(width=13, text=name), end=' ')
        # print matrix content
        for y in range(0, len(confMatrix[x])):
            if (not y in args.evalLabels):
                continue
            matrixFieldValue = getMatrixFieldValue(confMatrix, x, y, args)
            print(getColorEntry(matrixFieldValue, args) + "\b{text:>{width}.2f}  ".format(width=args.printRow,
                                                                                          text=matrixFieldValue) + args.nocol,
                  end=' ')
        # print prior
        print(getColorEntry(prior, args) + "\b{text:>{width}.4f} ".format(width=6, text=prior) + args.nocol)
    # print line
    print("\b{text:{fill}>{width}}".format(width=15, fill='-', text=" "), end=' ')
    for label in args.evalLabels:
        print("\b{text:{fill}>{width}}".format(width=args.printRow + 2, fill='-', text=" "), end=' ')
    print("\b{text:{fill}>{width}}".format(width=args.printRow + 3, fill='-', text=" "), end=' ')


# Print intersection-over-union scores for all classes.
def printClassScores(scoreList, instScoreList, args):
    if (args.quiet):
        return
    print(args.bold + "classes          IoU      nIoU" + args.nocol)
    print("--------------------------------")
    for label in args.evalLabels:
        if (id2label[label].ignoreInEval):
            continue
        labelName = str(id2label[label].name)
        iouStr = getColorEntry(scoreList[labelName], args) + "{val:>5.3f}".format(
            val=scoreList[labelName]) + args.nocol
        niouStr = getColorEntry(instScoreList[labelName], args) + "{val:>5.3f}".format(
            val=instScoreList[labelName]) + args.nocol
        print("{:<14}: ".format(labelName) + iouStr + "    " + niouStr)


# Print intersection-over-union scores for all categorys.
def printCategoryScores(scoreDict, instScoreDict, args):
    if (args.quiet):
        return
    print(args.bold + "categories       IoU      nIoU" + args.nocol)
    print("--------------------------------")
    for categoryName in scoreDict:
        if all(label.ignoreInEval for label in category2labels[categoryName]):
            continue
        iouStr = getColorEntry(scoreDict[categoryName], args) + "{val:>5.3f}".format(
            val=scoreDict[categoryName]) + args.nocol
        niouStr = getColorEntry(instScoreDict[categoryName], args) + "{val:>5.3f}".format(
            val=instScoreDict[categoryName]) + args.nocol
        print("{:<14}: ".format(categoryName) + iouStr + "    " + niouStr)


class EvalPixel():
    def __init__(self, args, predictionImgList = None, groundTruthImgList = None):
        self.args = args
        self.predictionImgList = predictionImgList
        self.groundTruthImgList = groundTruthImgList
        if predictionImgList is None or groundTruthImgList is None:
            self.groundTruthImgList,  self.predictionImgList = self.getDefaultData(self.args)

    # evaluate image in two lists
    def evaluateImgLists(self,predictionImgList, groundTruthImgList, args):
        if len(predictionImgList) != len(groundTruthImgList):
            printError("List of images for prediction and groundtruth are not of equal size.")
        confMatrix = generateMatrix(args)
        instStats = generateInstanceStats(args)
        perImageStats = {}
        nbPixels = 0

        if not args.quiet:
            print("Evaluating {} pairs of images...".format(len(predictionImgList)))

        # Evaluate all pairs of images and save them into a matrix
        for i in range(len(predictionImgList)):
            predictionImgFileName = predictionImgList[i]
            groundTruthImgFileName = groundTruthImgList[i]
            # print "Evaluate ", predictionImgFileName, "<>", groundTruthImgFileName
            nbPixels += self.evaluatePair(predictionImgFileName, groundTruthImgFileName, confMatrix, instStats,
                                     perImageStats, args)

            # sanity check
            if confMatrix.sum() != nbPixels:
                printError(
                    'Number of analyzed pixels and entries in confusion matrix disagree: contMatrix {}, pixels {}'.format(
                        confMatrix.sum(), nbPixels))

            if not args.quiet:
                print("\rImages Processed: {}".format(i + 1), end=' ')
                sys.stdout.flush()
        if not args.quiet:
            print("\n")

        # sanity check
        if confMatrix.sum() != nbPixels:
            printError(
                'Number of analyzed pixels and entries in confusion matrix disagree: contMatrix {}, pixels {}'.format(
                    confMatrix.sum(), nbPixels))

        # print confusion matrix
        if (not args.quiet):
            printConfMatrix(confMatrix, args)

        # Calculate IOU scores on class level from matrix
        classScoreList = {}
        for label in args.evalLabels:
            labelName = id2label[label].name
            classScoreList[labelName] = getIouScoreForLabel(label, confMatrix, args)

        # Calculate instance IOU scores on class level from matrix
        classInstScoreList = {}
        for label in args.evalLabels:
            labelName = id2label[label].name
            classInstScoreList[labelName] = getInstanceIouScoreForLabel(label, confMatrix, instStats, args)

        # Print IOU scores
        if (not args.quiet):
            print("")
            print("")
            printClassScores(classScoreList, classInstScoreList, args)
            iouAvgStr = getColorEntry(getScoreAverage(classScoreList, args), args) + "{avg:5.3f}".format(
                avg=getScoreAverage(classScoreList, args)) + args.nocol
            niouAvgStr = getColorEntry(getScoreAverage(classInstScoreList, args), args) + "{avg:5.3f}".format(
                avg=getScoreAverage(classInstScoreList, args)) + args.nocol
            print("--------------------------------")
            print("Score Average : " + iouAvgStr + "    " + niouAvgStr)
            print("--------------------------------")
            print("")

        # Calculate IOU scores on category level from matrix
        categoryScoreList = {}
        for category in category2labels.keys():
            categoryScoreList[category] = getIouScoreForCategory(category, confMatrix, args)

        # Calculate instance IOU scores on category level from matrix
        categoryInstScoreList = {}
        for category in category2labels.keys():
            categoryInstScoreList[category] = getInstanceIouScoreForCategory(category, confMatrix, instStats, args)

        # Print IOU scores
        if (not args.quiet):
            print("")
            printCategoryScores(categoryScoreList, categoryInstScoreList, args)
            iouAvgStr = getColorEntry(getScoreAverage(categoryScoreList, args), args) + "{avg:5.3f}".format(
                avg=getScoreAverage(categoryScoreList, args)) + args.nocol
            niouAvgStr = getColorEntry(getScoreAverage(categoryInstScoreList, args), args) + "{avg:5.3f}".format(
                avg=getScoreAverage(categoryInstScoreList, args)) + args.nocol
            print("--------------------------------")
            print("Score Average : " + iouAvgStr + "    " + niouAvgStr)
            print("--------------------------------")
            print("")

        # write result file
        allResultsDict = createResultDict(confMatrix, classScoreList, classInstScoreList, categoryScoreList,
                                          categoryInstScoreList, perImageStats, args)
        writeJSONFile(allResultsDict, args)

        # return confusion matrix
        return allResultsDict

    # Main evaluation method. Evaluates pairs of prediction and ground truth
    # images which are passed as arguments.
    def evaluatePair(self,predictionImgFileName, groundTruthImgFileName, confMatrix, instanceStats, perImageStats, args):
        # Loading all resources for evaluation.
        try:
            predictionImg = Image.open(predictionImgFileName)
            predictionNp = np.array(predictionImg)
        except:
            printError("Unable to load " + predictionImgFileName)
        try:
            groundTruthImg = Image.open(groundTruthImgFileName)
            groundTruthNp = np.array(groundTruthImg)
        except:
            printError("Unable to load " + groundTruthImgFileName)
        # load ground truth instances, if needed
        if args.evalInstLevelScore:
            groundTruthInstanceImgFileName = groundTruthImgFileName.replace("labelIds", "instanceIds")
            try:
                instanceImg = Image.open(groundTruthInstanceImgFileName)
                instanceNp = np.array(instanceImg)
            except:
                printError("Unable to load " + groundTruthInstanceImgFileName)

        # Check for equal image sizes
        if (predictionImg.size[0] != groundTruthImg.size[0]):
            printError(
                "Image widths of " + predictionImgFileName + " and " + groundTruthImgFileName + " are not equal.")
        if (predictionImg.size[1] != groundTruthImg.size[1]):
            printError(
                "Image heights of " + predictionImgFileName + " and " + groundTruthImgFileName + " are not equal.")
        if (len(predictionNp.shape) != 2):
            printError("Predicted image has multiple channels.")

        imgWidth = predictionImg.size[0]
        imgHeight = predictionImg.size[1]
        nbPixels = imgWidth * imgHeight

        # Evaluate images
        if (CSUPPORT):
            # using cython
            confMatrix = addToConfusionMatrix.cEvaluatePair(predictionNp, groundTruthNp, confMatrix, args.evalLabels)
        else:
            # the slower python way
            for (groundTruthImgPixel, predictionImgPixel) in izip(groundTruthImg.getdata(), predictionImg.getdata()):
                if (not groundTruthImgPixel in args.evalLabels):
                    printError("Unknown label with id {:}".format(groundTruthImgPixel))

                confMatrix[groundTruthImgPixel][predictionImgPixel] += 1

        if args.evalInstLevelScore:
            # Generate category masks
            categoryMasks = {}
            for category in instanceStats["categories"]:
                categoryMasks[category] = np.in1d(predictionNp,
                                                  instanceStats["categories"][category]["labelIds"]).reshape(
                    predictionNp.shape)

            instList = np.unique(instanceNp[instanceNp > 1000])
            for instId in instList:
                labelId = int(instId / 1000)
                label = id2label[labelId]
                if label.ignoreInEval:
                    continue

                mask = instanceNp == instId
                instSize = np.count_nonzero(mask)

                tp = np.count_nonzero(predictionNp[mask] == labelId)
                fn = instSize - tp

                weight = args.avgClassSize[label.name] / float(instSize)
                tpWeighted = float(tp) * weight
                fnWeighted = float(fn) * weight

                instanceStats["classes"][label.name]["tp"] += tp
                instanceStats["classes"][label.name]["fn"] += fn
                instanceStats["classes"][label.name]["tpWeighted"] += tpWeighted
                instanceStats["classes"][label.name]["fnWeighted"] += fnWeighted

                category = label.category
                if category in instanceStats["categories"]:
                    catTp = 0
                    catTp = np.count_nonzero(np.logical_and(mask, categoryMasks[category]))
                    catFn = instSize - catTp

                    catTpWeighted = float(catTp) * weight
                    catFnWeighted = float(catFn) * weight

                    instanceStats["categories"][category]["tp"] += catTp
                    instanceStats["categories"][category]["fn"] += catFn
                    instanceStats["categories"][category]["tpWeighted"] += catTpWeighted
                    instanceStats["categories"][category]["fnWeighted"] += catFnWeighted

        if args.evalPixelAccuracy:
            notIgnoredLabels = [l for l in args.evalLabels if not id2label[l].ignoreInEval]
            notIgnoredPixels = np.in1d(groundTruthNp, notIgnoredLabels, invert=True).reshape(groundTruthNp.shape)
            erroneousPixels = np.logical_and(notIgnoredPixels, (predictionNp != groundTruthNp))
            perImageStats[predictionImgFileName] = {}
            perImageStats[predictionImgFileName]["nbNotIgnoredPixels"] = np.count_nonzero(notIgnoredPixels)
            perImageStats[predictionImgFileName]["nbCorrectPixels"] = np.count_nonzero(erroneousPixels)

        return nbPixels


    # launch the process
    def run(self):
        self.evaluateImgLists(self.predictionImgList, self.groundTruthImgList, self.args)

    # get the default data
    def getDefaultData(self, args):
        groundTruthImgList, predictionImgList = [], []
        groundTruthImgList = glob.glob(args.groundTruthSearch)
        if not groundTruthImgList:
            printError("Cannot find any ground truth images to use for evaluation. Searched for: {}".format(
                args.groundTruthSearch))
        # get the corresponding prediction for each ground truth imag
        for gt in groundTruthImgList:
            predictionImgList.append(getPrediction(args, gt))
        return groundTruthImgList, predictionImgList


class CityScapeEvaluator(object):

    def evaluate(self, pred_dir=None, gt_dir=None):
        """
        :param pred_dir: directory of model output results(must be consistent with val directory)
        :param gt_dir: directory of  cityscape data(root)
        :return:
        """
        pred_path = pred_dir
        data_path = gt_dir
        print("evaluate the result...")
        args = CArgs(data_path=data_path, out_path=data_path, predict_path=pred_path)
        ob = EvalPixel(args)
        ob.run()


if __name__ == '__main__':
    # python cityscape_evaluator.py --gt_dir ~/DataSet/CityScape/gtFine/val
    #                               --pred_dir ~/Projects/PyTorchCV/val/results/seg/cityscape/test_dir/image/label
    parser = argparse.ArgumentParser()
    parser.add_argument('--gt_dir', default=None, type=str,
                        dest='gt_dir', help='The directory of ground truth.')
    parser.add_argument('--pred_dir', default=None, type=str,
                        dest='pred_dir', help='The directory of predicted labels.')

    args = parser.parse_args()

    cityscape_evaluator = CityScapeEvaluator()
    cityscape_evaluator.evaluate(pred_dir=args.pred_dir, gt_dir=args.gt_dir)
