import { Navigate, Route, Routes } from 'react-router';
import AppShell from '@/components/AppShell';
import AlertsPage from '@/pages/AlertsPage';
import AutomationPage from '@/pages/AutomationPage';
import BroadcastsPage from '@/pages/BroadcastsPage';
import SchedulesPage from '@/pages/SchedulesPage';
import SegmentsPage from '@/pages/SegmentsPage';
import ContactsPage from '@/pages/ContactsPage';
import DashboardPage from '@/pages/DashboardPage';
import GroupsPage from '@/pages/GroupsPage';
import InboxPage from '@/pages/InboxPage';
import InvitePage from '@/pages/InvitePage';
import LoginPage from '@/pages/LoginPage';
import NumbersPage from '@/pages/NumbersPage';
import OnboardingPage from '@/pages/OnboardingPage';
import SettingsPage from '@/pages/SettingsPage';
import TicketsPage from '@/pages/TicketsPage';

export default function App(): React.JSX.Element {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/onboarding" element={<OnboardingPage />} />
      <Route path="/invite/:token" element={<InvitePage />} />
      <Route element={<AppShell />}>
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/groups" element={<GroupsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/tickets" element={<TicketsPage />} />
        <Route path="/automation" element={<AutomationPage />} />
        <Route path="/broadcasts" element={<BroadcastsPage />} />
        <Route path="/schedules" element={<SchedulesPage />} />
        <Route path="/segments" element={<SegmentsPage />} />
        <Route path="/numbers" element={<NumbersPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
