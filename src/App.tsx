import { useEffect, useState } from 'react';
import './App.css';
import FlashDashboard from './components/FlashDashboard';
import LoginScreen from './components/LoginScreen';
import type { Operator } from './components/LoginScreen';
import ScanOrderScreen from './components/ScanOrderScreen';

const SESSION_OP_ID   = 'flashbench_operator_id';
const SESSION_OP_NAME = 'flashbench_operator_name';
const ORDER_KEY       = 'flashbench_order';
const THEME_KEY       = 'flashbench_theme';

export type Theme = 'dark' | 'light';

function App() {
  const [operatorId, setOperatorId] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_OP_ID)
  );
  const [operatorName, setOperatorName] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_OP_NAME)
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

  const handleSelectOperator = (op: Operator) => {
    const displayName = `${op.firstName.charAt(0).toUpperCase()}${op.firstName.slice(1).toLowerCase()} ${op.lastName.toUpperCase()}`;
    sessionStorage.setItem(SESSION_OP_ID, op.userUid);
    sessionStorage.setItem(SESSION_OP_NAME, displayName);
    setOperatorId(op.userUid);
    setOperatorName(displayName);
  };

  const handleConfirmOrder = (order: string) => {
    sessionStorage.setItem(ORDER_KEY, order);
    setOrderNumber(order);
  };

  const handleLogout = () => {
    sessionStorage.removeItem(SESSION_OP_ID);
    sessionStorage.removeItem(SESSION_OP_NAME);
    sessionStorage.removeItem(ORDER_KEY);
    setOperatorId(null);
    setOperatorName(null);
    setOrderNumber(null);
  };

  const handleBackToOperator = () => {
    setOperatorId(null);
    setOperatorName(null);
    setOrderNumber(null);
    sessionStorage.removeItem(SESSION_OP_ID);
    sessionStorage.removeItem(SESSION_OP_NAME);
    sessionStorage.removeItem(ORDER_KEY);
  };

  if (!operatorId || !operatorName) {
    return <LoginScreen onSelect={handleSelectOperator} theme={theme} onToggleTheme={toggleTheme} />;
  }

  if (!orderNumber) {
    return (
      <ScanOrderScreen
        operatorName={operatorName}
        onConfirm={handleConfirmOrder}
        onBack={handleBackToOperator}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
    );
  }

  return (
    <FlashDashboard
      operatorId={operatorId}
      operatorName={operatorName}
      orderNumber={orderNumber}
      onLogout={handleLogout}
      theme={theme}
      onToggleTheme={toggleTheme}
    />
  );
}

export default App;
