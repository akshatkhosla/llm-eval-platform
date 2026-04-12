import { Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { EvalsListPage } from './pages/EvalsListPage'
import { EvalDetailPage } from './pages/EvalDetailPage'
import { ComparePage } from './pages/ComparePage'
import { TrendsPage } from './pages/TrendsPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/evals" replace />} />
        <Route path="/evals" element={<EvalsListPage />} />
        <Route path="/evals/:id" element={<EvalDetailPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/trends" element={<TrendsPage />} />
      </Route>
    </Routes>
  )
}
