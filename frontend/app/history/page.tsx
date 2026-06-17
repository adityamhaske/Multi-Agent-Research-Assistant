'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface SessionHistory {
  session_id: string;
  status: string;
  prompt: string;
  research_depth: string;
  total_cost_usd: number;
  total_tokens_input: number;
  total_tokens_output: number;
  elapsed_seconds: number | null;
  created_at: string;
  message_count: number;
}

export default function HistoryPage() {
  const [sessions, setSessions] = useState<SessionHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSessions();
  }, []);

  const fetchSessions = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/research?limit=50', {
        headers: {
          'Authorization': 'Bearer test-token-123'
        }
      });
      if (!res.ok) throw new Error('Failed to fetch history');
      const data = await res.json();
      setSessions(data.sessions);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'PENDING': return <span className="badge badge-pending">Pending</span>;
      case 'RUNNING': return <span className="badge badge-running">Running</span>;
      case 'AWAITING_APPROVAL': return <span className="badge badge-awaiting">Awaiting Review</span>;
      case 'COMPLETED': return <span className="badge badge-completed">Completed</span>;
      case 'FAILED': return <span className="badge badge-failed">Failed</span>;
      default: return <span className="badge">{status}</span>;
    }
  };

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 animate-fade-in">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Research History</h1>
          <p className="text-[#94a3b8]">View and continue past research sessions.</p>
        </div>
        <Link href="/dashboard" className="btn-primary">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
          New Research
        </Link>
      </div>

      {error && (
        <div className="bg-[#f87171]/10 border border-[#f87171]/30 text-[#f87171] p-4 rounded-xl mb-6">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center items-center py-20">
          <div className="spinner"></div>
        </div>
      ) : sessions.length === 0 ? (
        <div className="card text-center py-16">
          <div className="w-16 h-16 bg-[#252836] rounded-full flex items-center justify-center mx-auto mb-4 text-[#64748b]">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No research history</h3>
          <p className="text-[#94a3b8] mb-6">You haven't run any research queries yet.</p>
          <Link href="/dashboard" className="btn-secondary">Start your first query</Link>
        </div>
      ) : (
        <div className="bg-[#1a1d27] border border-[rgba(255,255,255,0.08)] rounded-xl overflow-hidden">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#0f1117] text-[#94a3b8] text-sm uppercase tracking-wider">
                <th className="p-4 font-medium">Query</th>
                <th className="p-4 font-medium">Status</th>
                <th className="p-4 font-medium">Cost / Duration</th>
                <th className="p-4 font-medium">Date</th>
                <th className="p-4 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[rgba(255,255,255,0.08)]">
              {sessions.map(session => (
                <tr key={session.session_id} className="hover:bg-[#252836]/50 transition-colors">
                  <td className="p-4">
                    <div className="font-medium text-white line-clamp-1 mb-1">
                      {session.prompt}
                    </div>
                    <div className="text-xs text-[#64748b] flex items-center gap-3">
                      <span className="capitalize px-1.5 py-0.5 rounded bg-[#252836] border border-[rgba(255,255,255,0.05)]">
                        {session.research_depth}
                      </span>
                      {session.message_count > 0 && (
                        <span className="flex items-center gap-1 text-[#a78bfa]">
                          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>
                          {session.message_count} messages
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="p-4">
                    {getStatusBadge(session.status)}
                  </td>
                  <td className="p-4">
                    <div className="text-sm font-medium text-[#e2e8f0]">
                      ${session.total_cost_usd.toFixed(4)}
                    </div>
                    {session.elapsed_seconds && (
                      <div className="text-xs text-[#94a3b8]">
                        {(session.elapsed_seconds / 60).toFixed(1)} min
                      </div>
                    )}
                  </td>
                  <td className="p-4 text-sm text-[#94a3b8]">
                    {new Date(session.created_at).toLocaleDateString()}
                  </td>
                  <td className="p-4 text-right">
                    <Link 
                      href={`/session/${session.session_id}`}
                      className="inline-flex items-center gap-2 text-sm text-[#6c63ff] hover:text-[#a78bfa] font-medium transition-colors"
                    >
                      View
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
