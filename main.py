import sys
import os
import json
import tempfile
import xml.etree.ElementTree as ET
import math
import time
import threading
import requests
from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QPushButton, QListWidget, 
                               QCheckBox, QLineEdit, QTextEdit, QFileDialog,
                               QMessageBox, QSplitter, QGroupBox, QListWidgetItem,
                               QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
                               QSpinBox)
from PySide6.QtCore import Qt, QUrl, Signal, QObject, QTimer, Slot, QSettings
from PySide6.QtGui import QFont, QPalette, QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineSettings
from SimConnect import SimConnect, AircraftRequests, AircraftEvents

class UpdateSignals(QObject):
    log_signal = Signal(str)
    landing_signal = Signal(dict)
    waypoint_signal = Signal()
    position_signal = Signal(float, float, float, float)  # lat, lon, heading, altitude
    approach_signal = Signal(float, float, float)  # lat, lon, altitude for glide path
    altitude_update_signal = Signal(int, float)  # waypoint index, new altitude

class MSFSFlightMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MSFS Flight Monitor")
        self.setGeometry(50, 50, 1600, 1000)
        
        # Settings
        self.settings = QSettings("MSFSMonitor", "FlightMonitor")
        
        # Variables
        self.waypoints = []
        self.selected_waypoint_idx = None
        self.monitoring = False
        self.sm = None
        self.aq = None
        self.ae = None
        self.landing_history = self.load_landing_history()
        self.approach_path = []
        self.landing_data = {
            'touchdown_fpm': None,
            'touchdown_g': None,
            'touchdown_lat': None,
            'touchdown_lon': None,
            'on_ground': True,
            'timestamp': None,
            'airport': 'Unknown'
        }
        self.map_loaded = False
        self.last_altitude = 0
        self.show_vertical_profile = True
        
        # Signals
        self.signals = UpdateSignals()
        self.signals.log_signal.connect(self.add_log)
        self.signals.landing_signal.connect(self.update_landing_display)
        self.signals.waypoint_signal.connect(self.update_waypoint_list)
        self.signals.position_signal.connect(self.update_aircraft_position)
        self.signals.approach_signal.connect(self.add_approach_point)
        self.signals.altitude_update_signal.connect(self.update_waypoint_altitude)
        
        self.setup_modern_theme()
        self.create_ui()
        
    def setup_modern_theme(self):
        """Apply modern dark theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e2e;
            }
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: 'Segoe UI', Arial;
                font-size: 10pt;
            }
            QGroupBox {
                background-color: #313244;
                border: 2px solid #45475a;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: bold;
                color: #cdd6f4;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 10pt;
            }
            QPushButton:hover {
                background-color: #74c7ec;
            }
            QPushButton:pressed {
                background-color: #7287fd;
            }
            QPushButton:disabled {
                background-color: #45475a;
                color: #6c7086;
            }
            QLineEdit, QSpinBox {
                background-color: #313244;
                border: 2px solid #45475a;
                border-radius: 6px;
                padding: 6px;
                color: #cdd6f4;
            }
            QLineEdit:focus, QSpinBox:focus {
                border: 2px solid #89b4fa;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #45475a;
                border: none;
                width: 20px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #89b4fa;
            }
            QListWidget, QTableWidget {
                background-color: #313244;
                border: 2px solid #45475a;
                border-radius: 6px;
                color: #cdd6f4;
            }
            QListWidget::item:selected, QTableWidget::item:selected {
                background-color: #89b4fa;
                color: #1e1e2e;
            }
            QTextEdit {
                background-color: #313244;
                border: 2px solid #45475a;
                border-radius: 6px;
                color: #cdd6f4;
                padding: 4px;
            }
            QCheckBox {
                spacing: 8px;
                color: #cdd6f4;
            }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                border-radius: 4px;
                border: 2px solid #45475a;
                background-color: #313244;
            }
            QCheckBox::indicator:checked {
                background-color: #89b4fa;
                border: 2px solid #89b4fa;
            }
            QLabel {
                color: #cdd6f4;
            }
            QHeaderView::section {
                background-color: #45475a;
                color: #cdd6f4;
                padding: 6px;
                border: none;
                font-weight: bold;
            }
            QTabWidget::pane {
                border: 2px solid #45475a;
                border-radius: 6px;
                background-color: #313244;
            }
            QTabBar::tab {
                background-color: #313244;
                color: #cdd6f4;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }
            QTabBar::tab:selected {
                background-color: #89b4fa;
                color: #1e1e2e;
            }
        """)
        
    def create_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side - Map and Profile
        map_container = QWidget()
        map_layout = QVBoxLayout(map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)
        map_layout.setSpacing(5)
        
        # Map view
        self.map_view = QWebEngineView()
        settings = self.map_view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        self.map_view.loadFinished.connect(self.on_map_loaded)
        
        map_layout.addWidget(self.map_view, stretch=7)
        
        # Vertical Profile view
        self.profile_view = QWebEngineView()
        profile_settings = self.profile_view.settings()
        profile_settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        profile_settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        
        map_layout.addWidget(self.profile_view, stretch=3)
        
        splitter.addWidget(map_container)
        
        # Right side - Tabs
        tab_widget = QTabWidget()
        
        # Flight Plan Tab
        flight_tab = self.create_flight_plan_tab()
        tab_widget.addTab(flight_tab, "✈️ Flight Plan")
        
        # Landing Analysis Tab
        landing_tab = self.create_landing_tab()
        tab_widget.addTab(landing_tab, "🛬 Landing Analysis")
        
        # History Tab
        history_tab = self.create_history_tab()
        tab_widget.addTab(history_tab, "📊 History")
        
        splitter.addWidget(tab_widget)
        splitter.setSizes([1100, 500])
        
        main_layout.addWidget(splitter)
        
        QTimer.singleShot(100, self.init_map)
        QTimer.singleShot(200, self.init_profile)
        
    def create_flight_plan_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # Import section
        import_group = QGroupBox("📥 Import Flight Plan")
        import_layout = QVBoxLayout()
        
        btn_layout = QHBoxLayout()
        self.btn_import_pln = QPushButton("Import PLN File")
        self.btn_import_pln.clicked.connect(self.import_pln)
        btn_layout.addWidget(self.btn_import_pln)
        
        self.btn_import_simbrief = QPushButton("Import from SimBrief")
        self.btn_import_simbrief.clicked.connect(self.import_simbrief)
        btn_layout.addWidget(self.btn_import_simbrief)
        import_layout.addLayout(btn_layout)
        
        self.simbrief_input = QLineEdit()
        self.simbrief_input.setPlaceholderText("SimBrief Username/ID")
        saved_username = self.settings.value("simbrief_username", "")
        if saved_username:
            self.simbrief_input.setText(saved_username)
        import_layout.addWidget(self.simbrief_input)
        
        import_group.setLayout(import_layout)
        layout.addWidget(import_group)
        
        # Waypoints section
        waypoint_group = QGroupBox("📍 Route Waypoints")
        waypoint_layout = QVBoxLayout()
        
        self.waypoint_list = QListWidget()
        self.waypoint_list.currentRowChanged.connect(self.on_waypoint_select)
        waypoint_layout.addWidget(self.waypoint_list)
        
        self.wp_info_label = QLabel("Select a waypoint")
        self.wp_info_label.setWordWrap(True)
        waypoint_layout.addWidget(self.wp_info_label)
        
        # Altitude editor
        alt_layout = QHBoxLayout()
        alt_layout.addWidget(QLabel("Altitude (ft):"))
        self.altitude_spinbox = QSpinBox()
        self.altitude_spinbox.setRange(0, 50000)
        self.altitude_spinbox.setSingleStep(100)
        self.altitude_spinbox.setValue(0)
        self.altitude_spinbox.setEnabled(False)
        self.altitude_spinbox.valueChanged.connect(self.on_altitude_changed)
        alt_layout.addWidget(self.altitude_spinbox)
        waypoint_layout.addLayout(alt_layout)
        
        self.pause_checkbox = QCheckBox("⏸️ Pause sim at this waypoint")
        self.pause_checkbox.stateChanged.connect(self.toggle_pause_waypoint)
        waypoint_layout.addWidget(self.pause_checkbox)
        
        waypoint_group.setLayout(waypoint_layout)
        layout.addWidget(waypoint_group)
        
        # Profile options
        profile_group = QGroupBox("📊 Vertical Profile")
        profile_layout = QVBoxLayout()
        
        self.show_profile_checkbox = QCheckBox("Show Vertical Profile")
        self.show_profile_checkbox.setChecked(True)
        self.show_profile_checkbox.stateChanged.connect(self.toggle_profile_visibility)
        profile_layout.addWidget(self.show_profile_checkbox)
        
        profile_group.setLayout(profile_layout)
        layout.addWidget(profile_group)
        
        # SimConnect section
        simconnect_group = QGroupBox("🔗 SimConnect")
        simconnect_layout = QVBoxLayout()
        
        self.btn_connect = QPushButton("Connect to MSFS")
        self.btn_connect.clicked.connect(self.connect_simconnect)
        simconnect_layout.addWidget(self.btn_connect)
        
        self.btn_monitor = QPushButton("Start Monitoring")
        self.btn_monitor.clicked.connect(self.toggle_monitoring)
        self.btn_monitor.setEnabled(False)
        simconnect_layout.addWidget(self.btn_monitor)
        
        self.status_label = QLabel("Status: Disconnected")
        self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold; font-size: 11pt;")
        simconnect_layout.addWidget(self.status_label)
        
        simconnect_group.setLayout(simconnect_layout)
        layout.addWidget(simconnect_group)
        
        # Log section
        log_group = QGroupBox("📝 Activity Log")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        layout.addStretch()
        return tab
        
    def create_landing_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)
        
        # Current Landing
        current_group = QGroupBox("🎯 Current Landing")
        current_layout = QVBoxLayout()
        
        self.fpm_label = QLabel("Touchdown Rate: --- fpm")
        self.fpm_label.setStyleSheet("font-size: 18pt; font-weight: bold;")
        current_layout.addWidget(self.fpm_label)
        
        self.g_label = QLabel("G-Force: --- G")
        self.g_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        current_layout.addWidget(self.g_label)
        
        self.location_label = QLabel("Location: ---")
        self.location_label.setStyleSheet("font-size: 11pt;")
        current_layout.addWidget(self.location_label)
        
        self.runway_label = QLabel("Runway: ---")
        self.runway_label.setStyleSheet("font-size: 11pt;")
        current_layout.addWidget(self.runway_label)
        
        self.time_label = QLabel("Time: ---")
        self.time_label.setStyleSheet("font-size: 11pt;")
        current_layout.addWidget(self.time_label)
        
        btn_layout = QHBoxLayout()
        self.btn_zoom_landing = QPushButton("🔍 Zoom to Landing")
        self.btn_zoom_landing.clicked.connect(self.zoom_to_landing)
        btn_layout.addWidget(self.btn_zoom_landing)
        
        self.btn_reset_landing = QPushButton("Reset")
        self.btn_reset_landing.clicked.connect(self.reset_landing_data)
        btn_layout.addWidget(self.btn_reset_landing)
        current_layout.addLayout(btn_layout)
        
        current_group.setLayout(current_layout)
        layout.addWidget(current_group)
        
        # Approach Info
        approach_group = QGroupBox("📉 Approach Information")
        approach_layout = QVBoxLayout()
        
        self.approach_distance_label = QLabel("Approach Distance: --- nm")
        approach_layout.addWidget(self.approach_distance_label)
        
        self.approach_points_label = QLabel("Glide Path Points: 0")
        approach_layout.addWidget(self.approach_points_label)
        
        self.avg_descent_label = QLabel("Avg Descent Rate: --- fpm")
        approach_layout.addWidget(self.avg_descent_label)
        
        approach_group.setLayout(approach_layout)
        layout.addWidget(approach_group)
        
        # Landing Rating
        rating_group = QGroupBox("⭐ Landing Rating")
        rating_layout = QVBoxLayout()
        
        self.rating_label = QLabel("---")
        self.rating_label.setStyleSheet("font-size: 24pt; font-weight: bold; text-align: center;")
        self.rating_label.setAlignment(Qt.AlignCenter)
        rating_layout.addWidget(self.rating_label)
        
        self.rating_text_label = QLabel("Complete a landing to see rating")
        self.rating_text_label.setAlignment(Qt.AlignCenter)
        rating_layout.addWidget(self.rating_text_label)
        
        rating_group.setLayout(rating_layout)
        layout.addWidget(rating_group)
        
        layout.addStretch()
        return tab
        
    def create_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        history_group = QGroupBox("📜 Landing History")
        history_layout = QVBoxLayout()
        
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(6)
        self.history_table.setHorizontalHeaderLabels(["Date/Time", "FPM", "G-Force", "Rating", "Location", "Airport"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        
        history_layout.addWidget(self.history_table)
        
        btn_layout = QHBoxLayout()
        self.btn_clear_history = QPushButton("Clear History")
        self.btn_clear_history.clicked.connect(self.clear_history)
        btn_layout.addWidget(self.btn_clear_history)
        
        self.btn_export_history = QPushButton("Export to CSV")
        self.btn_export_history.clicked.connect(self.export_history)
        btn_layout.addWidget(self.btn_export_history)
        
        history_layout.addLayout(btn_layout)
        
        history_group.setLayout(history_layout)
        layout.addWidget(history_group)
        
        self.update_history_table()
        return tab
        
    def init_map(self):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" 
                  integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" 
                  crossorigin=""/>
            <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
                    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
                    crossorigin=""></script>
            <style>
                body { margin: 0; padding: 0; overflow: hidden; }
                #map { width: 100vw; height: 100vh; background: #1e1e2e; }
                .aircraft-icon { font-size: 28px; text-align: center; line-height: 30px; }
                .waypoint-label {
                    background: rgba(137, 180, 250, 0.9);
                    border: none;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-weight: bold;
                    color: #1e1e2e;
                    font-size: 12px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.3);
                }
            </style>
        </head>
        <body>
            <div id="map"></div>
            <script>
                var map = L.map('map', { zoomControl: true }).setView([50.8503, 4.3517], 6);
                
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '© OpenStreetMap',
                    maxZoom: 19
                }).addTo(map);
                
                var markers = [], routeLine = null, aircraftMarker = null;
                var breadcrumbLine = null, breadcrumbs = [];
                var landingMarkers = [], approachLine = null, approachPoints = [];
                var touchdownMarker = null;
                var waypointLabels = [];
                
                function updateRoute(waypoints) {
                    markers.forEach(m => map.removeLayer(m));
                    waypointLabels.forEach(l => map.removeLayer(l));
                    markers = [];
                    waypointLabels = [];
                    if (routeLine) map.removeLayer(routeLine);
                    if (waypoints.length === 0) return;
                    
                    var coords = [];
                    waypoints.forEach((wp, idx) => {
                        var color = wp.pause ? 'red' : 'blue';
                        var marker = L.circleMarker([wp.lat, wp.lon], {
                            radius: 8, fillColor: color, color: '#fff',
                            weight: 2, opacity: 1, fillOpacity: 0.8
                        }).addTo(map);
                        
                        var popupText = '<b>' + (idx + 1) + '. ' + wp.id + '</b><br>Lat: ' + 
                                       wp.lat.toFixed(6) + '<br>Lon: ' + wp.lon.toFixed(6);
                        if (wp.altitude) {
                            popupText += '<br>Alt: ' + wp.altitude.toFixed(0) + ' ft';
                        }
                        marker.bindPopup(popupText);
                        
                        // Add label
                        var label = L.marker([wp.lat, wp.lon], {
                            icon: L.divIcon({
                                className: 'waypoint-label',
                                html: wp.id,
                                iconSize: null
                            }),
                            zIndexOffset: 100
                        }).addTo(map);
                        
                        markers.push(marker);
                        waypointLabels.push(label);
                        coords.push([wp.lat, wp.lon]);
                    });
                    
                    if (coords.length > 1) {
                        routeLine = L.polyline(coords, {
                            color: '#89b4fa', weight: 3, opacity: 0.6, dashArray: '10, 5'
                        }).addTo(map);
                        map.fitBounds(routeLine.getBounds(), { padding: [50, 50] });
                    }
                }
                
                function updateAircraftPosition(lat, lon, heading, alt) {
                    if (aircraftMarker) map.removeLayer(aircraftMarker);
                    
                    breadcrumbs.push([lat, lon]);
                    if (breadcrumbs.length > 500) breadcrumbs.shift();
                    
                    if (breadcrumbLine) map.removeLayer(breadcrumbLine);
                    if (breadcrumbs.length > 1) {
                        breadcrumbLine = L.polyline(breadcrumbs, {
                            color: '#f38ba8', weight: 3, opacity: 0.7
                        }).addTo(map);
                    }
                    
                    var planeIcon = L.divIcon({
                        html: '<div class="aircraft-icon" style="transform: rotate(' + heading + 'deg);">✈️</div>',
                        className: '', iconSize: [30, 30], iconAnchor: [15, 15]
                    });
                    
                    aircraftMarker = L.marker([lat, lon], { 
                        icon: planeIcon, zIndexOffset: 1000
                    }).addTo(map);
                    aircraftMarker.bindPopup('Aircraft<br>Alt: ' + alt.toFixed(0) + ' ft<br>Hdg: ' + heading.toFixed(0) + '°');
                }
                
                function addApproachPoint(lat, lon, alt) {
                    approachPoints.push([lat, lon, alt]);
                    if (approachLine) map.removeLayer(approachLine);
                    
                    if (approachPoints.length > 1) {
                        var coords = approachPoints.map(p => [p[0], p[1]]);
                        approachLine = L.polyline(coords, {
                            color: '#f9e2af', weight: 4, opacity: 0.8
                        }).addTo(map);
                    }
                }
                
                function addLandingMarker(lat, lon, fpm, g, isDetailed) {
                    var color = Math.abs(fpm) < 100 ? '#a6e3a1' : (Math.abs(fpm) < 300 ? '#f9e2af' : '#f38ba8');
                    
                    if (isDetailed && touchdownMarker) {
                        map.removeLayer(touchdownMarker);
                    }
                    
                    var marker = L.circleMarker([lat, lon], {
                        radius: isDetailed ? 15 : 12,
                        fillColor: color, color: '#fff',
                        weight: 3, opacity: 1, fillOpacity: 0.9
                    }).addTo(map);
                    
                    marker.bindPopup('<b>🛬 TOUCHDOWN</b><br>Rate: ' + fpm.toFixed(0) + ' fpm<br>' +
                                   'G-Force: ' + g.toFixed(2) + ' G<br>' +
                                   'Lat: ' + lat.toFixed(6) + '<br>Lon: ' + lon.toFixed(6)).openPopup();
                    
                    if (isDetailed) {
                        touchdownMarker = marker;
                        map.setView([lat, lon], 17);
                    } else {
                        landingMarkers.push(marker);
                    }
                }
                
                function zoomToLanding(lat, lon) {
                    map.setView([lat, lon], 18, { animate: true, duration: 1 });
                }
                
                function clearBreadcrumbs() {
                    breadcrumbs = [];
                    approachPoints = [];
                    if (breadcrumbLine) { map.removeLayer(breadcrumbLine); breadcrumbLine = null; }
                    if (approachLine) { map.removeLayer(approachLine); approachLine = null; }
                    if (touchdownMarker) { map.removeLayer(touchdownMarker); touchdownMarker = null; }
                }
            </script>
        </body>
        </html>
        """
        
        self.map_file = os.path.join(tempfile.gettempdir(), 'msfs_map.html')
        with open(self.map_file, 'w', encoding='utf-8') as f:
            f.write(html)
        
        self.map_view.setUrl(QUrl.fromLocalFile(self.map_file))
        self.add_log("Initializing map...")
        
    def init_profile(self):
        """Initialize vertical profile view"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
            <style>
                body { 
                    margin: 0; 
                    padding: 10px; 
                    background: #1e1e2e; 
                    overflow: hidden;
                }
                #container { 
                    width: 100%; 
                    height: calc(100vh - 20px);
                }
            </style>
        </head>
        <body>
            <canvas id="profileChart"></canvas>
            <script>
                var chart = null;
                var currentPosition = null;
                
                function updateProfile(waypoints) {
                    if (waypoints.length === 0) return;
                    
                    // Calculate cumulative distance
                    var distances = [0];
                    var totalDist = 0;
                    for (var i = 1; i < waypoints.length; i++) {
                        var dist = calculateDistance(
                            waypoints[i-1].lat, waypoints[i-1].lon,
                            waypoints[i].lat, waypoints[i].lon
                        );
                        totalDist += dist;
                        distances.push(totalDist);
                    }
                    
                    // Prepare data
                    var labels = waypoints.map((wp, i) => wp.id);
                    var altitudes = waypoints.map(wp => wp.altitude || 0);
                    
                    // Calculate 3-degree glide slope for last segment
                    var glideSlopeData = [];
                    if (waypoints.length >= 2) {
                        var lastIdx = waypoints.length - 1;
                        var destAlt = waypoints[lastIdx].altitude || 0;
                        
                        // 3-degree glide slope: 300 ft per nm
                        for (var i = 0; i < waypoints.length; i++) {
                            var distToLast = distances[lastIdx] - distances[i];
                            var glideSlopeAlt = destAlt + (distToLast * 300);
                            glideSlopeData.push(glideSlopeAlt);
                        }
                    }
                    
                    var ctx = document.getElementById('profileChart').getContext('2d');
                    
                    if (chart) chart.destroy();
                    
                    var datasets = [{
                        label: 'Flight Plan',
                        data: altitudes,
                        borderColor: '#89b4fa',
                        backgroundColor: 'rgba(137, 180, 250, 0.1)',
                        fill: true,
                        tension: 0.3,
                        pointRadius: 6,
                        pointBackgroundColor: '#89b4fa'
                    }];
                    
                    if (glideSlopeData.length > 0) {
                        datasets.push({
                            label: '3° Glide Slope',
                            data: glideSlopeData,
                            borderColor: '#f9e2af',
                            borderDash: [5, 5],
                            fill: false,
                            tension: 0,
                            pointRadius: 0
                        });
                    }
                    
                    chart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: labels,
                            datasets: datasets
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: {
                                    display: true,
                                    labels: { color: '#cdd6f4', font: { size: 12 } }
                                },
                                title: {
                                    display: true,
                                    text: 'Vertical Profile',
                                    color: '#cdd6f4',
                                    font: { size: 14, weight: 'bold' }
                                }
                            },
                            scales: {
                                x: {
                                    title: { display: true, text: 'Waypoints', color: '#cdd6f4' },
                                    ticks: { color: '#cdd6f4' },
                                    grid: { color: '#45475a' }
                                },
                                y: {
                                    title: { display: true, text: 'Altitude (ft)', color: '#cdd6f4' },
                                    ticks: { color: '#cdd6f4' },
                                    grid: { color: '#45475a' },
                                    beginAtZero: true
                                }
                            }
                        }
                    });
                }
                
                function updateAircraftOnProfile(waypointIndex, altitude) {
                    if (!chart) return;
                    currentPosition = { index: waypointIndex, altitude: altitude };
                    // This could be enhanced to show aircraft position on the chart
                }
                
                function calculateDistance(lat1, lon1, lat2, lon2) {
                    var R = 3440.065; // nautical miles
                    var dLat = (lat2 - lat1) * Math.PI / 180;
                    var dLon = (lon2 - lon1) * Math.PI / 180;
                    var a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
                            Math.sin(dLon/2) * Math.sin(dLon/2);
                    var c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                    return R * c;
                }
            </script>
        </body>
        </html>
        """
        
        self.profile_file = os.path.join(tempfile.gettempdir(), 'msfs_profile.html')
        with open(self.profile_file, 'w', encoding='utf-8') as f:
            f.write(html)
        
        self.profile_view.setUrl(QUrl.fromLocalFile(self.profile_file))
        
    @Slot(bool)
    def on_map_loaded(self, success):
        if success:
            self.map_loaded = True
            self.add_log("Map loaded successfully")
        else:
            self.add_log("Map failed to load")
            
    def update_map(self):
        if not self.map_loaded:
            QTimer.singleShot(500, self.update_map)
            return
        if not self.waypoints:
            return
        waypoints_json = json.dumps(self.waypoints)
        self.map_view.page().runJavaScript(f"updateRoute({waypoints_json});")
        
    def update_profile(self):
        if not self.waypoints:
            return
        waypoints_json = json.dumps(self.waypoints)
        self.profile_view.page().runJavaScript(f"updateProfile({waypoints_json});")
        
    def toggle_profile_visibility(self, state):
        self.show_vertical_profile = (state == Qt.Checked)
        if self.show_vertical_profile:
            self.profile_view.show()
            QTimer.singleShot(100, self.update_profile)
        else:
            self.profile_view.hide()
        
    @Slot(str)
    def add_log(self, message):
        timestamp = time.strftime('%H:%M:%S')
        self.log_text.append(f"<span style='color: #89b4fa;'>[{timestamp}]</span> {message}")
        
    def import_pln(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Select MSFS PLN file", "", "Flight Plan files (*.pln)")
        if filename:
            try:
                tree = ET.parse(filename)
                root = tree.getroot()
                self.waypoints = []
                
                for atp in root.findall('.//ATCWaypoint'):
                    wp_id = atp.get('id')
                    world_pos = atp.find('.//WorldPosition').text.split(',')
                    
                    # Try to get altitude from PLN
                    altitude = 0
                    alt_elem = atp.find('.//ATCAltitude')
                    if alt_elem is not None and alt_elem.text:
                        try:
                            altitude = float(alt_elem.text)
                        except:
                            altitude = 0
                    
                    self.waypoints.append({
                        'id': wp_id,
                        'lat': float(world_pos[0]),
                        'lon': float(world_pos[1]),
                        'altitude': altitude,
                        'pause': False
                    })
                
                self.update_waypoint_list()
                QTimer.singleShot(100, self.update_map)
                QTimer.singleShot(200, self.update_profile)
                self.signals.log_signal.emit(f"✅ Loaded {len(self.waypoints)} waypoints from PLN")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load PLN: {str(e)}")
                
    def import_simbrief(self):
        username = self.simbrief_input.text()
        if not username:
            QMessageBox.warning(self, "Warning", "Please enter SimBrief username")
            return
            
        # Save username
        self.settings.setValue("simbrief_username", username)
        
        try:
            url = f"https://www.simbrief.com/api/xml.fetcher.php?username={username}&json=1"
            response = requests.get(url)
            data = response.json()
            
            if 'fetch' in data and data['fetch']['status'] == 'Success':
                self.waypoints = []
                for fix in data.get('navlog', {}).get('fix', []):
                    altitude = 0
                    try:
                        altitude = float(fix.get('altitude_feet', 0))
                    except:
                        altitude = 0
                        
                    self.waypoints.append({
                        'id': fix.get('ident', 'Unknown'),
                        'lat': float(fix.get('pos_lat', 0)),
                        'lon': float(fix.get('pos_long', 0)),
                        'altitude': altitude,
                        'pause': False
                    })
                
                self.update_waypoint_list()
                QTimer.singleShot(100, self.update_map)
                QTimer.singleShot(200, self.update_profile)
                self.signals.log_signal.emit(f"✅ Loaded {len(self.waypoints)} waypoints from SimBrief")
            else:
                QMessageBox.critical(self, "Error", "Failed to fetch SimBrief plan")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"SimBrief import failed: {str(e)}")
            
    def update_waypoint_list(self):
        self.waypoint_list.clear()
        for i, wp in enumerate(self.waypoints):
            pause = " ⏸️" if wp['pause'] else ""
            alt_str = f" ({wp.get('altitude', 0):.0f} ft)" if wp.get('altitude', 0) > 0 else ""
            self.waypoint_list.addItem(f"{i+1}. {wp['id']}{alt_str}{pause}")
            
    def on_waypoint_select(self, row):
        if 0 <= row < len(self.waypoints):
            self.selected_waypoint_idx = row
            wp = self.waypoints[row]
            alt_str = f"<br>Altitude: {wp.get('altitude', 0):.0f} ft" if wp.get('altitude', 0) > 0 else ""
            self.wp_info_label.setText(f"<b>{wp['id']}</b><br>Coordinates: {wp['lat']:.6f}, {wp['lon']:.6f}{alt_str}")
            
            self.pause_checkbox.blockSignals(True)
            self.pause_checkbox.setChecked(wp['pause'])
            self.pause_checkbox.blockSignals(False)
            self.pause_checkbox.setEnabled(True)
            
            self.altitude_spinbox.blockSignals(True)
            self.altitude_spinbox.setValue(int(wp.get('altitude', 0)))
            self.altitude_spinbox.blockSignals(False)
            self.altitude_spinbox.setEnabled(True)
        else:
            self.selected_waypoint_idx = None
            self.wp_info_label.setText("Select a waypoint")
            self.pause_checkbox.setEnabled(False)
            self.altitude_spinbox.setEnabled(False)
            
    def on_altitude_changed(self, value):
        if self.selected_waypoint_idx is not None:
            self.waypoints[self.selected_waypoint_idx]['altitude'] = value
            self.update_waypoint_list()
            QTimer.singleShot(100, self.update_map)
            QTimer.singleShot(200, self.update_profile)
            self.waypoint_list.setCurrentRow(self.selected_waypoint_idx)
            
    @Slot(int, float)
    def update_waypoint_altitude(self, idx, altitude):
        if 0 <= idx < len(self.waypoints):
            self.waypoints[idx]['altitude'] = altitude
            
    def toggle_pause_waypoint(self, state):
        if self.selected_waypoint_idx is not None:
            self.waypoints[self.selected_waypoint_idx]['pause'] = (state == Qt.Checked)
            self.update_waypoint_list()
            QTimer.singleShot(100, self.update_map)
            self.waypoint_list.setCurrentRow(self.selected_waypoint_idx)
            
    def connect_simconnect(self):
        try:
            self.sm = SimConnect()
            self.aq = AircraftRequests(self.sm)
            self.ae = AircraftEvents(self.sm)
            
            self.status_label.setText("Status: Connected ✅")
            self.status_label.setStyleSheet("color: #a6e3a1; font-weight: bold; font-size: 11pt;")
            self.btn_monitor.setEnabled(True)
            self.btn_connect.setEnabled(False)
            self.signals.log_signal.emit("✅ Connected to MSFS")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to connect to SimConnect: {str(e)}")
            self.signals.log_signal.emit(f"❌ Connection failed: {str(e)}")
            
    def toggle_monitoring(self):
        if not self.monitoring:
            self.monitoring = True
            self.btn_monitor.setText("Stop Monitoring")
            self.signals.log_signal.emit("🚀 Started monitoring flight")
            self.map_view.page().runJavaScript("clearBreadcrumbs();")
            self.approach_path = []
            
            self.monitor_thread = threading.Thread(target=self.monitor_flight, daemon=True)
            self.monitor_thread.start()
        else:
            self.monitoring = False
            self.btn_monitor.setText("Start Monitoring")
            self.signals.log_signal.emit("⏹️ Stopped monitoring")
            
    def monitor_flight(self):
        was_airborne = False
        last_check_time = time.time()
        recording_approach = False
        
        while self.monitoring:
            try:
                lat = self.aq.get("PLANE_LATITUDE")
                lon = self.aq.get("PLANE_LONGITUDE")
                alt = self.aq.get("PLANE_ALTITUDE")
                vs = self.aq.get("VERTICAL_SPEED")
                on_ground = self.aq.get("SIM_ON_GROUND")
                g_force = self.aq.get("G_FORCE")
                heading = self.aq.get("PLANE_HEADING_DEGREES_TRUE")
                
                # Update aircraft position
                self.signals.position_signal.emit(lat, lon, heading, alt)
                
                # Check for takeoff
                if on_ground == 0 and not was_airborne:
                    was_airborne = True
                    self.landing_data['on_ground'] = False
                    self.signals.log_signal.emit("🛫 Aircraft airborne")
                
                # Record approach (below 3000ft AGL and descending)
                if was_airborne and alt < 3000 and vs < -100 and not on_ground:
                    if not recording_approach:
                        recording_approach = True
                        self.signals.log_signal.emit("📉 Recording approach")
                    self.signals.approach_signal.emit(lat, lon, alt)
                
                # Check for landing
                if on_ground == 1 and was_airborne and not self.landing_data['on_ground']:
                    self.landing_data['touchdown_fpm'] = vs
                    self.landing_data['touchdown_g'] = g_force
                    self.landing_data['touchdown_lat'] = lat
                    self.landing_data['touchdown_lon'] = lon
                    self.landing_data['on_ground'] = True
                    self.landing_data['timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Calculate approach stats
                    if len(self.approach_path) > 1:
                        start_point = self.approach_path[0]
                        distance = self.calculate_distance(start_point[0], start_point[1], lat, lon)
                        self.landing_data['approach_distance'] = distance
                        
                        # Average descent rate
                        total_vs = sum([abs(p[2] - self.approach_path[i-1][2]) for i, p in enumerate(self.approach_path) if i > 0])
                        avg_vs = total_vs / (len(self.approach_path) - 1) if len(self.approach_path) > 1 else 0
                        self.landing_data['avg_descent'] = avg_vs
                    
                    self.save_landing_to_history(self.landing_data.copy())
                    self.signals.landing_signal.emit(self.landing_data.copy())
                    self.signals.log_signal.emit(f"🛬 Landing: {vs:.0f} fpm, {g_force:.2f} G")
                    
                    # Add detailed landing marker
                    script = f"addLandingMarker({lat}, {lon}, {vs}, {g_force}, true);"
                    self.map_view.page().runJavaScript(script)
                    
                    recording_approach = False
                
                # Check waypoint proximity
                current_time = time.time()
                if current_time - last_check_time > 2:
                    for wp in self.waypoints:
                        if wp['pause']:
                            distance = self.calculate_distance(lat, lon, wp['lat'], wp['lon'])
                            if distance < 0.5:
                                self.ae.event("PAUSE_SET", 1)
                                self.signals.log_signal.emit(f"⏸️ Reached {wp['id']} - Paused")
                                wp['pause'] = False
                                self.signals.waypoint_signal.emit()
                    last_check_time = current_time
                
                self.last_altitude = alt
                time.sleep(1)
                
            except Exception as e:
                self.signals.log_signal.emit(f"⚠️ Monitoring error: {str(e)}")
                time.sleep(2)
                
    @Slot(float, float, float, float)
    def update_aircraft_position(self, lat, lon, heading, alt):
        if self.map_loaded:
            script = f"updateAircraftPosition({lat}, {lon}, {heading}, {alt});"
            self.map_view.page().runJavaScript(script)
            
    @Slot(float, float, float)
    def add_approach_point(self, lat, lon, alt):
        self.approach_path.append((lat, lon, alt))
        script = f"addApproachPoint({lat}, {lon}, {alt});"
        self.map_view.page().runJavaScript(script)
        self.approach_points_label.setText(f"Glide Path Points: {len(self.approach_path)}")
                
    def calculate_distance(self, lat1, lon1, lat2, lon2):
        R = 3440.065
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c
        
    def get_landing_rating(self, fpm, g_force):
        """
        Improved landing rating based on both FPM and G-force
        Weighting: 60% FPM, 40% G-force
        """
        abs_fpm = abs(fpm)
        
        # FPM scoring (0-100)
        if abs_fpm < 100:
            fpm_score = 100
        elif abs_fpm < 200:
            fpm_score = 85
        elif abs_fpm < 300:
            fpm_score = 70
        elif abs_fpm < 400:
            fpm_score = 50
        elif abs_fpm < 600:
            fpm_score = 30
        else:
            fpm_score = 10
            
        # G-force scoring (0-100)
        if g_force < 1.3:
            g_score = 100
        elif g_force < 1.5:
            g_score = 85
        elif g_force < 1.8:
            g_score = 70
        elif g_force < 2.0:
            g_score = 50
        elif g_force < 2.5:
            g_score = 30
        else:
            g_score = 10
            
        # Combined score (weighted)
        combined_score = (fpm_score * 0.6) + (g_score * 0.4)
        
        # Determine rating
        if combined_score >= 95:
            return "⭐⭐⭐⭐⭐", "PERFECT - Butter Landing!", "#a6e3a1"
        elif combined_score >= 80:
            return "⭐⭐⭐⭐", "Excellent Landing", "#a6e3a1"
        elif combined_score >= 65:
            return "⭐⭐⭐", "Good Landing", "#f9e2af"
        elif combined_score >= 45:
            return "⭐⭐", "Acceptable Landing", "#fab387"
        else:
            return "⭐", "Hard Landing - Check Aircraft!", "#f38ba8"
        
    @Slot(dict)
    def update_landing_display(self, data):
        fpm = data['touchdown_fpm']
        g = data['touchdown_g']
        
        if fpm is not None:
            self.fpm_label.setText(f"Touchdown Rate: {fpm:.0f} fpm")
            color = "#a6e3a1" if abs(fpm) < 100 else ("#f9e2af" if abs(fpm) < 300 else "#f38ba8")
            self.fpm_label.setStyleSheet(f"color: {color}; font-size: 18pt; font-weight: bold;")
            
        if g is not None:
            self.g_label.setText(f"G-Force: {g:.2f} G")
            
        if data['touchdown_lat'] and data['touchdown_lon']:
            self.location_label.setText(f"Location: {data['touchdown_lat']:.6f}, {data['touchdown_lon']:.6f}")
            
        if data.get('timestamp'):
            self.time_label.setText(f"Time: {data['timestamp']}")
            
        # Update approach info
        if data.get('approach_distance'):
            self.approach_distance_label.setText(f"Approach Distance: {data['approach_distance']:.2f} nm")
        if data.get('avg_descent'):
            self.avg_descent_label.setText(f"Avg Descent Rate: {data['avg_descent']:.0f} fpm")
            
        # Update rating
        if fpm and g:
            rating, text, color = self.get_landing_rating(fpm, g)
            self.rating_label.setText(rating)
            self.rating_label.setStyleSheet(f"color: {color}; font-size: 24pt; font-weight: bold;")
            self.rating_text_label.setText(text)
            self.rating_text_label.setStyleSheet(f"color: {color}; font-size: 12pt;")
            
    def zoom_to_landing(self):
        if self.landing_data['touchdown_lat'] and self.landing_data['touchdown_lon']:
            lat = self.landing_data['touchdown_lat']
            lon = self.landing_data['touchdown_lon']
            script = f"zoomToLanding({lat}, {lon});"
            self.map_view.page().runJavaScript(script)
            self.signals.log_signal.emit("🔍 Zoomed to landing location")
        else:
            QMessageBox.information(self, "Info", "No landing data available")
            
    def reset_landing_data(self):
        self.landing_data = {
            'touchdown_fpm': None, 'touchdown_g': None,
            'touchdown_lat': None, 'touchdown_lon': None,
            'on_ground': True, 'timestamp': None, 'airport': 'Unknown'
        }
        self.approach_path = []
        self.fpm_label.setText("Touchdown Rate: --- fpm")
        self.fpm_label.setStyleSheet("font-size: 18pt; font-weight: bold;")
        self.g_label.setText("G-Force: --- G")
        self.g_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        self.location_label.setText("Location: ---")
        self.time_label.setText("Time: ---")
        self.runway_label.setText("Runway: ---")
        self.approach_distance_label.setText("Approach Distance: --- nm")
        self.approach_points_label.setText("Glide Path Points: 0")
        self.avg_descent_label.setText("Avg Descent Rate: --- fpm")
        self.rating_label.setText("---")
        self.rating_text_label.setText("Complete a landing to see rating")
        self.signals.log_signal.emit("🔄 Landing data reset")
        
    def load_landing_history(self):
        history_file = os.path.join(os.path.expanduser("~"), ".msfs_landing_history.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    return json.load(f)
            except:
                return []
        return []
        
    def save_landing_history(self):
        history_file = os.path.join(os.path.expanduser("~"), ".msfs_landing_history.json")
        try:
            with open(history_file, 'w') as f:
                json.dump(self.landing_history, f, indent=2)
        except Exception as e:
            self.signals.log_signal.emit(f"⚠️ Failed to save history: {str(e)}")
            
    def save_landing_to_history(self, data):
        rating, text, _ = self.get_landing_rating(data['touchdown_fpm'], data['touchdown_g'])
        history_entry = {
            'timestamp': data['timestamp'],
            'fpm': data['touchdown_fpm'],
            'g_force': data['touchdown_g'],
            'lat': data['touchdown_lat'],
            'lon': data['touchdown_lon'],
            'airport': data.get('airport', 'Unknown'),
            'rating': rating,
            'rating_text': text
        }
        self.landing_history.insert(0, history_entry)
        if len(self.landing_history) > 100:
            self.landing_history = self.landing_history[:100]
        self.save_landing_history()
        self.update_history_table()
        
    def update_history_table(self):
        self.history_table.setRowCount(len(self.landing_history))
        for i, entry in enumerate(self.landing_history):
            self.history_table.setItem(i, 0, QTableWidgetItem(entry['timestamp']))
            self.history_table.setItem(i, 1, QTableWidgetItem(f"{entry['fpm']:.0f}"))
            self.history_table.setItem(i, 2, QTableWidgetItem(f"{entry['g_force']:.2f}"))
            self.history_table.setItem(i, 3, QTableWidgetItem(entry['rating']))
            self.history_table.setItem(i, 4, QTableWidgetItem(f"{entry['lat']:.4f}, {entry['lon']:.4f}"))
            self.history_table.setItem(i, 5, QTableWidgetItem(entry['airport']))
            
    def clear_history(self):
        reply = QMessageBox.question(self, 'Clear History', 
                                     'Are you sure you want to clear all landing history?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.landing_history = []
            self.save_landing_history()
            self.update_history_table()
            self.signals.log_signal.emit("🗑️ Landing history cleared")
            
    def export_history(self):
        if not self.landing_history:
            QMessageBox.information(self, "Info", "No landing history to export")
            return
            
        filename, _ = QFileDialog.getSaveFileName(self, "Export Landing History", 
                                                  "landing_history.csv", "CSV files (*.csv)")
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write("Date/Time,FPM,G-Force,Rating,Latitude,Longitude,Airport\n")
                    for entry in self.landing_history:
                        f.write(f"{entry['timestamp']},{entry['fpm']:.0f},{entry['g_force']:.2f},"
                               f"{entry['rating']},{entry['lat']:.6f},{entry['lon']:.6f},{entry['airport']}\n")
                self.signals.log_signal.emit(f"💾 Exported history to {filename}")
                QMessageBox.information(self, "Success", "Landing history exported successfully")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Export failed: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MSFSFlightMonitor()
    window.show()
    sys.exit(app.exec())