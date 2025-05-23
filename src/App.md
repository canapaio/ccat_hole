# React Frontend Application

## Overview
Main React component for the CCAT Hole web interface. Provides file upload functionality and integration with backend services.

## Key Features
- User authentication flow
- File upload with progress tracking
- Integration with backend API
- Material-UI components

## Main Components
- `App`: Root component managing application state
- `useDropzone`: Handles file drag-and-drop functionality
- `Axios`: HTTP client for API calls

## State Management
- `isAuthenticated`: Tracks user login status
- `loading`: Shows loading indicators
- `message`: Displays status messages
- `files`: Stores uploaded files list
- `uploadProgress`: Tracks file upload percentage

## API Configuration
- Base URL configurable via environment variables
- Automatic JWT token injection

## Dependencies
- React
- Material-UI
- Axios
- react-dropzone