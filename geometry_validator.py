# -*- coding: utf-8 -*-
"""
/***************************************************************************
 GeometryValidator
                                 A QGIS plugin
 This plugin checks whether the geometries in a layer are valid
                              -------------------
        begin                : 2017-12-20
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Jeremy Benn Associates Ltd.
        email                : peet.whittaker@jbaconsulting.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
from PyQt4.QtCore import QSettings, QTranslator, qVersion, QCoreApplication, QVariant, QObject, pyqtSignal, QThread
from PyQt4.QtGui import QAction, QIcon, QMessageBox
# Initialize Qt resources from file resources.py
import resources
# Import the code for the dialog
from geometry_validator_dialog import GeometryValidatorDialog
import os.path
# Custom imports
from qgis.core import QgsMapLayerRegistry, QgsPoint, QgsGeometry, QgsFeature, QgsFields, QgsField, QgsVectorLayer
from qgis.gui import QgsMapLayerProxyModel
from shapely import validation, wkt
import re
import traceback

class GeometryValidator:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'GeometryValidator_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)

            if qVersion() > '4.3.3':
                QCoreApplication.installTranslator(self.translator)


        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&Geometry Validator')
        # TODO: We are going to let the user set this up in a future iteration
        self.toolbar = self.iface.addToolBar(u'GeometryValidator')
        self.toolbar.setObjectName(u'GeometryValidator')

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('GeometryValidator', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        # Create the dialog (after translation) and keep reference
        self.dlg = GeometryValidatorDialog()

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.toolbar.addAction(action)

        if add_to_menu:
            self.iface.addPluginToVectorMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_path = ':/plugins/GeometryValidator/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Validate geometries'),
            callback=self.run,
            parent=self.iface.mainWindow())

        # Connect run button to process method
        self.dlg.runButton.clicked.connect(self.process)


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginVectorMenu(
                self.tr(u'&Geometry Validator'),
                action)
            self.iface.removeToolBarIcon(action)
        # remove the toolbar
        del self.toolbar


    def run(self):
        """Run method that performs all the real work"""

        # Filter input layer combo box to only show vector layers
        self.dlg.comboBoxInputLayer.setFilters(QgsMapLayerProxyModel.HasGeometry)

        # Reset progress bar
        self.dlg.progressBar.setValue(0)

        # Show the dialog
        self.dlg.show()


    def process(self):
        # Get selected layer and process if provided
        layer = self.dlg.comboBoxInputLayer.currentLayer()
        if layer:
            self.startWorker(layer)


    def startWorker(self, layer):
        # Initialize worker with selected layer
        worker = Worker(layer)

        # Disable run button
        self.dlg.runButton.setEnabled(False)

        # Ensure worker is killed if dialog is "killed" (either by the user clicking Cancel, closing the dialog, or by pressing the Escape key)
        self.dlg.rejected.connect(worker.kill)

        # Initialize new thread and move worker to it
        thread = QThread(self.dlg)
        worker.moveToThread(thread)

        # Connect signals to slots
        worker.finished.connect(self.workerFinished)
        worker.error.connect(self.workerError)
        worker.progress.connect(self.dlg.progressBar.setValue)
        thread.started.connect(worker.run)

        # Start thread and run worker
        thread.start()

        # Save reference to thread and worker
        self.thread = thread
        self.worker = worker


    def workerFinished(self, ret):
        # Clean up the worker and thread
        self.worker.deleteLater()
        self.thread.quit()
        self.thread.wait()
        self.thread.deleteLater()

        # Process return value
        if ret is not None:
            numErrors, errorLayer, errorLayerName = ret

            # Add output layer to map canvas if errors detected and display message box
            if numErrors > 0:
                errorLayer.updateExtents()
                QgsMapLayerRegistry.instance().addMapLayer(errorLayer)
                errorMsg = "Detected %g invalid geometries!\n\nPlease see the '%s' layer for details." % (numErrors, errorLayerName)
                QMessageBox.warning(self.dlg, 'Geometry Validator', errorMsg, QMessageBox.Ok)
            else:
                QMessageBox.information(self.dlg, 'Geometry Validator', "No invalid geometries detected :)", QMessageBox.Ok)

        # Re-enable run button
        self.dlg.runButton.setEnabled(True)


    def workerError(self, ex, exception_string):
        # Display error message box
        QMessageBox.critical(self.dlg, 'Geometry Validator', exception_string, QMessageBox.Ok)


class Worker(QObject):
    """Worker to run long-running process in separate thread; taken from:
    https://snorfalorpagus.net/blog/2013/12/07/multithreading-in-qgis-python-plugins"""
    def __init__(self, layer):
        QObject.__init__(self)
        self.layer = layer
        self.killed = False

    def run(self):
        ret = None
        try:
            # Reset current progress
            self.progress.emit(0)

            # Initialize output vector layer for invalid point locations
            # NOTE: Must set CRS in vector layer path URI, rather than using setCrs() method;
            #       see: https://gis.stackexchange.com/a/77500
            layerCrsWkt = self.layer.crs().toWkt()
            errorLayerName = 'validation_errors'
            errorLayer = QgsVectorLayer("Point?crs=%s" % layerCrsWkt, errorLayerName, 'memory')

            # Add attribute fields to output layer
            dataProvider = errorLayer.dataProvider()
            dataProvider.addAttributes([QgsField('Reason', QVariant.String)])
            errorLayer.updateFields()

            # Iterate over each feature in the input layer
            numErrors = 0
            total = 100.0 / self.layer.featureCount() if self.layer.featureCount() > 0 else 1
            features = self.layer.getFeatures()
            for current, feature in enumerate(features, 1):
                # Check whether kill request received
                if self.killed is True:
                    break

                # Get geometry from current feature and check whether it is valid
                geom = feature.geometry()
                if not geom.isEmpty() and not geom.isGeosValid():
                    # Use shapely to get validation error reason
                    # NOTE: Cannot use the geom.validateGeometry() method here as it does not seem to work correctly
                    # NOTE: Shapely method uses the GEOSisValidReason_r method internally, see:
                    #       https://trac.osgeo.org/geos/browser/trunk/capi/geos_ts_c.cpp#L954
                    geomWkt = geom.exportToWkt()
                    shape = wkt.loads(geomWkt)
                    validationStr = validation.explain_validity(shape)

                    # Parse validation error reason to get location co-ordinates
                    matches = re.search('\[([\w\d.\-+]+)\s+([\w\d.\-+]+)\]', validationStr)
                    coordX = matches.group(1)
                    coordY = matches.group(2)

                    # Convert co-ordinates to point geometry
                    errorPoint = QgsPoint(float(coordX), float(coordY))
                    errorGeom = QgsGeometry.fromPoint(errorPoint)

                    # Create new feature from point geometry and attribute with validation error reason
                    errorFeat = QgsFeature()
                    errorFeat.setGeometry(errorGeom)
                    errorFeat.setAttributes([validationStr])
                    dataProvider.addFeatures([errorFeat])

                    # Update error count
                    numErrors += 1

                # Update current progress
                self.progress.emit(int(current * total))

            # Set return value
            if self.killed is False:
                ret = numErrors, errorLayer, errorLayerName
        except Exception, ex:
            # Propagate exception upstream
            self.error.emit(ex, traceback.format_exc())

        # Propagate return value
        self.finished.emit(ret)

    def kill(self):
        self.killed = True

    # Define signals
    finished = pyqtSignal(object)
    error = pyqtSignal(Exception, basestring)
    progress = pyqtSignal(int)
