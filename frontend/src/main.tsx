import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import AppErrorBoundary from './AppErrorBoundary';
import './styles.css';
import { registerServiceWorker } from './lib/push';
import { installErrorReporting } from './lib/errors';

registerServiceWorker();
installErrorReporting();

const root = document.getElementById('root')!;
createRoot(root).render(<StrictMode><AppErrorBoundary><App /></AppErrorBoundary></StrictMode>);
