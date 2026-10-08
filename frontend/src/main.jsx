import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applyTheme, savedTheme } from './theme';
import './style.css';
import './theme.css';

applyTheme(savedTheme());
createRoot(document.getElementById('root')).render(<App />);
