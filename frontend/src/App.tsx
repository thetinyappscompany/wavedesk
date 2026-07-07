import { Navigate, Route, Routes } from 'react-router';
import LoginPage from '@/pages/LoginPage';
import NumbersPage from '@/pages/NumbersPage';

export default function App(): React.JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/numbers" element={<NumbersPage />} />
      {/* Inbox (3-pane) lands with the next epics; login is the default. */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
