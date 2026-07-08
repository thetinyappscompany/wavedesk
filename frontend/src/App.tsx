import { Navigate, Route, Routes } from 'react-router';
import AppShell from '@/components/AppShell';
import ContactsPage from '@/pages/ContactsPage';
import InboxPage from '@/pages/InboxPage';
import LoginPage from '@/pages/LoginPage';
import NumbersPage from '@/pages/NumbersPage';

export default function App(): React.JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppShell />}>
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/numbers" element={<NumbersPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
