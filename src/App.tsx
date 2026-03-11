import { useEffect, useState } from 'react';
import './App.css';
import FlashDashboard from './components/FlashDashboard';
import LoginScreen from './components/LoginScreen';
import ScanOrderScreen from './components/ScanOrderScreen';

const SESSION_KEY = 'flashbench_operator';
const ORDER_KEY   = 'flashbench_order';
const THEME_KEY   = 'flashbench_theme';

export type Theme = 'dark' | 'light';

function App() {
  const [operator, setOperator] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_KEY)
  );
  const [orderNumber, setOrderNumber] = useState<string | null>(
    () => sessionStorage.getItem(ORDER_KEY)
  );
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem(THEME_KEY) as Theme) || 'dark'
  );

  // Apply data-theme to <html> on mount and when changed
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));

  const handleSelectOperator = (op: string) => {
    sessionStorage.setItem(SESSION_KEY, op);
    setOperator(op);
  };

  const handleConfirmOrder = (order: string) => {
    sessionStorage.setItem(ORDER_KEY, order);
    setOrderNumber(order);
  };

  const handleLogout = () => {
    sessionStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(ORDER_KEY);
    setOperator(null);
    setOrderNumber(null);
  };

  const handleBackToOperator = () => {
    setOperator(null);
    setOrderNumber(null);
    sessionStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(ORDER_KEY);
  };

  if (!operator) {
    return <LoginScreen onSelect={handleSelectOperator} theme={theme} onToggleTheme={toggleTheme} />;
  }

  if (!orderNumber) {
    return (
      <ScanOrderScreen
        operator={operator}
        onConfirm={handleConfirmOrder}
        onBack={handleBackToOperator}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
    );
  }

  return (
    <FlashDashboard
      operator={operator}
      orderNumber={orderNumber}
      onLogout={handleLogout}
      theme={theme}
      onToggleTheme={toggleTheme}
    />
  );
}

export default App;
