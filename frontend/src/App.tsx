import { Navigate, Route, Routes } from 'react-router';
import LoginPage from '@/pages/LoginPage';

export default function App(): React.JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Inbox shell lands in Phase 1; everything redirects to login for now. */}
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
