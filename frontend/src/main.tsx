import React from 'react';
import {createRoot} from 'react-dom/client';
import {Display} from './Display';
import {Manage} from './Manage';
import './style.css';

const path=location.pathname;
createRoot(document.getElementById('root')!).render(<React.StrictMode>{path.startsWith('/display')?<Display/>:<Manage/>}</React.StrictMode>);
