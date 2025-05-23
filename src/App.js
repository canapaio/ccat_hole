
import React, { useState, useEffect } from 'react';
import {
  Container,
  Paper,
  Typography,
  Button,
  Box,
  Alert,
  LinearProgress,
  Card,
  CardContent,
  Grid
} from '@mui/material';
import { useDropzone } from 'react-dropzone';
import axios from 'axios';

// Configurazione API
const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

// Configurazione Axios
const api = axios.create({
  baseURL: API_BASE_URL,
});

// Interceptor per aggiungere token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [files, setFiles] = useState([]);
  const [uploadProgress, setUploadProgress] = useState(0);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      setIsAuthenticated(true);
      loadFiles();
    }
  }, []);

  const login = async () => {
    try {
      const response = await api.post('/auth/login', {
        username: 'admin',
        password: 'password'
      });
      localStorage.setItem('token', response.data.access_token);
      setIsAuthenticated(true);
      loadFiles();
    } catch (error) {
      setMessage('Login failed: ' + error.response?.data?.detail);
    }
  };

  const loadFiles = async () => {
    try {
      const response = await api.get('/files');
      setFiles(response.data.files || []);
    } catch (error) {
      console.error('Failed to load files:', error);
    }
  };

  const onDrop = async (acceptedFiles) => {
    if (acceptedFiles.length === 0) return;

    const file = acceptedFiles[0];
    const formData = new FormData();
    formData.append('file', file);

    setLoading(true);
    setUploadProgress(0);

    try {
      // Upload file
      const uploadResponse = await api.post('/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        onUploadProgress: (progressEvent) => {
          const percentCompleted = Math.round(
            (progressEvent.loaded * 100) / progressEvent.total
          );
          setUploadProgress(percentCompleted);
        },
      });

      setMessage(`File uploaded successfully: ${uploadResponse.data.filename}`);

      // Auto-import to CCAT
      const importResponse = await api.post('/import', {
        file_id: uploadResponse.data.file_id,
        context_metadata: {
          filename: file.name,
          size: file.size,
          type: file.type
        }
      });

      setMessage(
        `File imported to CCAT: ${importResponse.data.message} (Context ID: ${importResponse.data.ccat_context_id})`
      );

      loadFiles();
    } catch (error) {
      setMessage('Error: ' + (error.response?.data?.detail || error.message));
    } finally {
      setLoading(false);
      setUploadProgress(0);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    multiple: false,
    accept: {
      'text/*': ['.txt', '.md', '.csv'],
      'application/pdf': ['.pdf'],
      'application/json': ['.json']
    }
  });

  if (!isAuthenticated) {
    return (
      <Container maxWidth="sm" sx={{ mt: 4 }}>
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="h4" gutterBottom>
            CCAT File Manager
          </Typography>
          <Button variant="contained" onClick={login} size="large">
            Login
          </Button>
        </Paper>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ mt: 4 }}>
      <Typography variant="h3" gutterBottom>
        CCAT Integrated File Manager
      </Typography>

      {/* Upload Area */}
      <Paper sx={{ p: 4, mb: 4 }}>
        <div
          {...getRootProps()}
          style={{
            border: '2px dashed #ccc',
            borderRadius: '4px',
            padding: '40px',
            textAlign: 'center',
            cursor: 'pointer',
            backgroundColor: isDragActive ? '#f5f5f5' : 'transparent'
          }}
        >
          <input {...getInputProps()} />
          {isDragActive ? (
            <Typography>Drop the file here...</Typography>
          ) : (
            <Typography>
              Drag & drop a file here, or click to select
              <br />
              Supported: TXT, MD, CSV, PDF, JSON
            </Typography>
          )}
        </div>

        {loading && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress variant="determinate" value={uploadProgress} />
            <Typography variant="body2" sx={{ mt: 1 }}>
              {uploadProgress}% uploaded
            </Typography>
          </Box>
        )}
      </Paper>

      {/* Messages */}
      {message && (
        <Alert 
          severity={message.includes('Error') ? 'error' : 'success'} 
          sx={{ mb: 4 }}
          onClose={() => setMessage('')}
        >
          {message}
        </Alert>
      )}

      {/* Files List */}
      <Typography variant="h5" gutterBottom>
        Your Files
      </Typography>
      <Grid container spacing={2}>
        {files.map((file) => (
          <Grid item xs={12} md={6} lg={4} key={file.id}>
            <Card>
              <CardContent>
                <Typography variant="h6" noWrap>
                  {file.filename}
                </Typography>
                <Typography color="text.secondary">
                  Status: {file.status}
                </Typography>
                <Typography color="text.secondary">
                  Uploaded: {new Date(file.created_at).toLocaleString()}
                </Typography>
                {file.ccat_context_id && (
                  <Typography color="success.main">
                    CCAT Context: {file.ccat_context_id}
                  </Typography>
                )}
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Container>
  );
}

export default App;