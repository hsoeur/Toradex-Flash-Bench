import { useState } from 'react';
import './App.css';
import FlashDashboard from './components/FlashDashboard';
import LoginScreen from './components/LoginScreen';

const SESSION_KEY = 'flashbench_operator';

function App() {
  const [operator, setOperator] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_KEY)
  );

  const handleSelect = (op: string) => {
    sessionStorage.setItem(SESSION_KEY, op);
    setOperator(op);
  };

  const handleLogout = () => {
    sessionStorage.removeItem(SESSION_KEY);
    setOperator(null);
  };

  if (!operator) {
    return <LoginScreen onSelect={handleSelect} />;
  }

  return <FlashDashboard operator={operator} onLogout={handleLogout} />;
}

export default App;
