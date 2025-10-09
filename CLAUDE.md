# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ADS-BBY is an aircraft tracking display system that visualizes nearby aircraft data on an LED matrix display. It combines data from OpenSky Network (free, low-frequency updates) with FlightAware AeroAPI (paid, detailed information) to create a hybrid data source for real-time aircraft tracking.

## Development Commands

### Package Management
This project uses `uv` for Python package management.

```bash
# Install dependencies
uv sync

# Add a new dependency
uv add <package-name>

# Run the main application
uv run python main.py
```

## Architecture Overview

The system follows a multi-layered architecture with clear separation of concerns:

### Core Components

1. **Hybrid API Layer** (`api/Hybrid.py`)
   - Manages dual data sources: OpenSky (low-cost, basic data) and FlightAware AeroAPI (detailed flight info)
   - Polls for aircraft within a specified radius from a home location
   - Handles refresh rates (30-second intervals for OpenSky)
   - Provides observable stream of current aircraft with automatic supplemental data loading

2. **Aircraft Model** (`models/Aircraft.py`)
   - Represents individual aircraft with OpenSky state vector properties
   - Key properties: tail number, airline/flight number, airspeed, aircraft type, altitude, heading
   - Placeholder fields for FlightAware supplemental data (origin/destination, estimated times)
   - Delegates position calculations to Position class for extrapolation
   - Provides display helpers (name formatting, category descriptions, unit conversions)

3. **Position Model** (`models/Position.py`)
   - Encapsulates geographic position with velocity and heading
   - Handles all spatial calculations: distance (Haversine formula), bearing, approach/departure detection
   - Provides position extrapolation based on velocity and heading for smooth updates between API polls
   - Used by both Aircraft model and rendering system for location-based operations

4. **Rendering System** (`display/Renderer.py`)
   - Manages display output to RGB LED matrix via `rgbmatrix` library
   - Uses PIL for frame composition
   - Dual display modes: primary (closest aircraft with extended info) and secondary (truncated list of nearby aircraft)
   - Handles smooth animations for list reordering
   - Implements screensaver mode when no aircraft are present
   - Compositor pattern for positioning multiple render components in frame buffer

5. **Main Entry Point** (`main.py`)
   - Orchestrates system initialization
   - Sets up API authentication and threading
   - Manages refresh intervals between data loading and rendering
   - Coordinates data flow from APIs through models to display

## Key Design Patterns

- **Hybrid Data Source**: Combines low-frequency free data with on-demand paid data for cost-effective real-time tracking
- **Separation of Concerns**: Position class handles all spatial calculations independently from aircraft data
- **Position Extrapolation**: Position objects project current location between API updates for smooth display
- **Compositor Pattern**: Display system uses separate renderers for large/small aircraft views, composed into final frame
- **Strobing Animation**: Visual feedback for approaching (white/green) vs departing (white/red) aircraft

## Dependencies

- `opensky-api`: Free aircraft tracking API (installed from GitHub)
- `pillow`: PIL image library for rendering and frame composition
- `rgbmatrix`: LED matrix control library (commented out, needs manual installation from hzeller/rpi-rgb-led-matrix)