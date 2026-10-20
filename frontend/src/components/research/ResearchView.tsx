import React, { useState } from 'react';
import {
  TrendingUp,
  Search,
  MessageSquare,
  Sparkles,
  AlertCircle,
  ExternalLink,
  Flame,
  BarChart2,
  Calendar,
  Layers,
} from 'lucide-react';
import { fetchRedditResearch, fetchTrends } from '../../api/dashboardApi';
import { ResearchResponse, ResearchSignalItem } from '../../types/dashboard';

export const ResearchView: React.FC = () => {
  const [sourceType, setSourceType] = useState<'multi_source' | 'reddit'>('multi_source');
  const [topic, setTopic] = useState('AI video tools');
  const [subreddit, setSubreddit] = useState('');
  const [timeRange, setTimeRange] = useState('month');
  const [limit, setLimit] = useState(10);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<ResearchResponse | null>(null);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim() && !subreddit.trim()) {
      setError('Please provide at least a topic or a subreddit to search.');
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      if (sourceType === 'multi_source') {
        if (!topic.trim()) {
          throw new Error('Multi-source trend discovery requires a topic keyword.');
        }
        const data = await fetchTrends({
          topic: topic.trim(),
          subreddit: subreddit.trim() || undefined,
          timeRange,
          limit,
        });
        setResponse(data);
      } else {
        const data = await fetchRedditResearch({
          topic: topic.trim() || undefined,
          subreddit: subreddit.trim() || undefined,
          timeRange,
          limit,
        });
        setResponse(data);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Research query failed';
      setError(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: '1600px', margin: '0 auto', padding: '1.5rem', width: '100%' }}>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem' }}>
        <h2
          style={{
            fontSize: '1.25rem',
            fontWeight: 700,
            color: 'var(--text-primary)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <TrendingUp size={22} color="var(--accent-primary)" />
          Research & Trend Intelligence
        </h2>
        <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
          Discover trending topics, viral hooks, and real-time audience demand across Reddit and Google Trends.
        </p>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '380px 1fr',
          gap: '1.5rem',
          alignItems: 'start',
        }}
      >
        {/* Left: Query Configuration Card */}
        <section aria-label="Research Parameters">
          <div className="creator-card">
            <h3
              style={{
                fontSize: '0.9375rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                marginBottom: '1rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <Search size={16} color="var(--accent-primary)" />
              Search Parameters
            </h3>

            {/* Source Type Selector */}
            <div style={{ marginBottom: '1rem' }}>
              <label
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  color: 'var(--text-secondary)',
                  display: 'block',
                  marginBottom: '0.375rem',
                }}
              >
                Intelligence Source
              </label>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '0.5rem',
                }}
              >
                <button
                  type="button"
                  onClick={() => setSourceType('multi_source')}
                  style={{
                    padding: '8px',
                    borderRadius: '6px',
                    border: `1px solid ${
                      sourceType === 'multi_source'
                        ? 'var(--accent-primary)'
                        : 'var(--border-color)'
                    }`,
                    backgroundColor:
                      sourceType === 'multi_source'
                        ? 'rgba(99, 102, 241, 0.12)'
                        : 'var(--bg-primary)',
                    color:
                      sourceType === 'multi_source'
                        ? 'var(--text-primary)'
                        : 'var(--text-secondary)',
                    fontSize: '0.75rem',
                    fontWeight: sourceType === 'multi_source' ? 600 : 400,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.375rem',
                  }}
                >
                  <Sparkles size={14} />
                  Multi-Source
                </button>
                <button
                  type="button"
                  onClick={() => setSourceType('reddit')}
                  style={{
                    padding: '8px',
                    borderRadius: '6px',
                    border: `1px solid ${
                      sourceType === 'reddit' ? 'var(--accent-primary)' : 'var(--border-color)'
                    }`,
                    backgroundColor:
                      sourceType === 'reddit'
                        ? 'rgba(99, 102, 241, 0.12)'
                        : 'var(--bg-primary)',
                    color:
                      sourceType === 'reddit' ? 'var(--text-primary)' : 'var(--text-secondary)',
                    fontSize: '0.75rem',
                    fontWeight: sourceType === 'reddit' ? 600 : 400,
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.375rem',
                  }}
                >
                  <MessageSquare size={14} />
                  Reddit Only
                </button>
              </div>
            </div>

            <form onSubmit={handleSearch} style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
              {/* Topic Input */}
              <div>
                <label
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    display: 'block',
                    marginBottom: '0.25rem',
                  }}
                >
                  Topic or Keyword {sourceType === 'multi_source' ? '*' : ''}
                </label>
                <input
                  type="text"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g. AI automation, cinematic lighting"
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    fontSize: '0.8125rem',
                    outline: 'none',
                  }}
                />
              </div>

              {/* Subreddit Filter */}
              <div>
                <label
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    display: 'block',
                    marginBottom: '0.25rem',
                  }}
                >
                  Subreddit (Optional)
                </label>
                <input
                  type="text"
                  value={subreddit}
                  onChange={(e) => setSubreddit(e.target.value)}
                  placeholder="e.g. artificial, singularity"
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    fontSize: '0.8125rem',
                    outline: 'none',
                  }}
                />
              </div>

              {/* Time Range */}
              <div>
                <label
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    display: 'block',
                    marginBottom: '0.25rem',
                  }}
                >
                  Time Filter
                </label>
                <select
                  value={timeRange}
                  onChange={(e) => setTimeRange(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    backgroundColor: 'var(--bg-primary)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-primary)',
                    fontSize: '0.8125rem',
                    outline: 'none',
                  }}
                >
                  <option value="hour">Past Hour</option>
                  <option value="day">Past 24 Hours</option>
                  <option value="week">Past Week</option>
                  <option value="month">Past Month</option>
                  <option value="year">Past Year</option>
                  <option value="all">All Time</option>
                </select>
              </div>

              {/* Limit */}
              <div>
                <label
                  style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-secondary)',
                    display: 'block',
                    marginBottom: '0.25rem',
                  }}
                >
                  Max Results ({limit})
                </label>
                <input
                  type="range"
                  min="5"
                  max="30"
                  step="5"
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  style={{ width: '100%', accentColor: 'var(--accent-primary)' }}
                />
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="btn-primary"
                style={{
                  marginTop: '0.5rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '0.5rem',
                }}
              >
                <Search size={14} className={isLoading ? 'animate-spin' : ''} />
                <span>{isLoading ? 'Searching...' : 'Discover Trends'}</span>
              </button>
            </form>
          </div>
        </section>

        {/* Right: Results Display */}
        <section aria-label="Discovered Signals">
          <div className="creator-card">
            {/* Results Header */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                paddingBottom: '0.75rem',
                borderBottom: '1px solid var(--border-color)',
                marginBottom: '1rem',
              }}
            >
              <div>
                <span
                  style={{
                    fontSize: '0.875rem',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                  }}
                >
                  Trend Signals
                </span>
                {response && (
                  <span
                    style={{
                      fontSize: '0.75rem',
                      color: 'var(--text-muted)',
                      marginLeft: '0.5rem',
                    }}
                  >
                    ({response.total_results} signals from {response.source})
                  </span>
                )}
              </div>
              {response?.retrieved_at && (
                <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                  Retrieved: {new Date(response.retrieved_at).toLocaleTimeString()}
                </span>
              )}
            </div>

            {/* Results Content */}
            {isLoading ? (
              <div style={{ padding: '3.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                <TrendingUp size={28} className="animate-spin" style={{ margin: '0 auto 0.75rem' }} />
                <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                  Scraping and ranking trend signals...
                </p>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
                  Evaluating keyword volume, freshness, and engagement velocity.
                </p>
              </div>
            ) : error ? (
              <div
                style={{
                  padding: '2rem',
                  textAlign: 'center',
                  color: 'var(--danger)',
                  backgroundColor: 'rgba(239, 68, 68, 0.05)',
                  borderRadius: '8px',
                }}
              >
                <AlertCircle size={24} style={{ margin: '0 auto 0.5rem' }} />
                <p style={{ fontSize: '0.875rem' }}>{error}</p>
              </div>
            ) : !response || response.results.length === 0 ? (
              <div style={{ padding: '3.5rem', textAlign: 'center', color: 'var(--text-muted)' }}>
                <Search size={32} style={{ margin: '0 auto 0.75rem', opacity: 0.4 }} />
                <p style={{ fontSize: '0.9375rem', fontWeight: 500, color: 'var(--text-secondary)' }}>
                  No research signals yet
                </p>
                <p style={{ fontSize: '0.8125rem', marginTop: '0.25rem' }}>
                  Execute a search to uncover discussions and breakout search queries.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
                {response.results.map((signal, sIdx) => (
                  <div
                    key={sIdx}
                    style={{
                      padding: '1rem',
                      borderRadius: '8px',
                      backgroundColor: 'var(--bg-primary)',
                      border: '1px solid var(--border-color)',
                      transition: 'border-color 0.15s',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'flex-start',
                        gap: '1rem',
                      }}
                    >
                      <h4
                        style={{
                          fontSize: '0.9375rem',
                          fontWeight: 600,
                          color: 'var(--text-primary)',
                          lineHeight: 1.4,
                        }}
                      >
                        {signal.topic}
                      </h4>
                      <span
                        style={{
                          fontSize: '0.6875rem',
                          fontWeight: 600,
                          padding: '2px 8px',
                          borderRadius: '4px',
                          backgroundColor:
                            signal.source.toLowerCase() === 'reddit'
                              ? 'rgba(239, 68, 68, 0.12)'
                              : 'rgba(99, 102, 241, 0.12)',
                          color:
                            signal.source.toLowerCase() === 'reddit'
                              ? '#fca5a5'
                              : 'var(--accent-primary)',
                          border: '1px solid var(--border-color)',
                          textTransform: 'uppercase',
                        }}
                      >
                        {signal.source}
                      </span>
                    </div>

                    <p
                      style={{
                        fontSize: '0.8125rem',
                        color: 'var(--text-secondary)',
                        marginTop: '0.375rem',
                        lineHeight: 1.4,
                      }}
                    >
                      {signal.search_volume_or_signal}
                    </p>

                    {/* Metadata Badges */}
                    <div
                      style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        alignItems: 'center',
                        gap: '0.75rem',
                        marginTop: '0.75rem',
                        paddingTop: '0.5rem',
                        borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                        fontSize: '0.75rem',
                        color: 'var(--text-muted)',
                      }}
                    >
                      <span>
                        Relevance: <strong style={{ color: 'var(--text-primary)' }}>{Math.round(signal.relevance * 100)}%</strong>
                      </span>
                      <span>
                        Confidence: <strong style={{ color: 'var(--text-primary)' }}>{Math.round(signal.confidence * 100)}%</strong>
                      </span>
                      {signal.opportunity_score !== undefined && signal.opportunity_score !== null && (
                        <span>
                          Opportunity:{' '}
                          <strong style={{ color: 'var(--success)' }}>
                            {signal.opportunity_score}/100
                          </strong>
                        </span>
                      )}
                      {signal.competition && (
                        <span>
                          Competition: <strong style={{ color: 'var(--text-primary)' }}>{signal.competition}</strong>
                        </span>
                      )}
                      <span>
                        Freshness: <strong style={{ color: 'var(--text-secondary)' }}>{signal.freshness}</strong>
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
};
