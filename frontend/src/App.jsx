import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const currency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
})

function money(cents) {
  return currency.format((cents ?? 0) / 100)
}

function titleForConversation(conversation) {
  if (conversation?.last_message) {
    return conversation.last_message
  }
  return `Chat ${conversation?.conversation_id?.slice(0, 8) ?? ''}`
}

function parseSse(buffer) {
  const events = []
  const blocks = buffer.split('\n\n')
  const rest = blocks.pop() ?? ''

  for (const block of blocks) {
    let event = 'message'
    const data = []

    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) {
        event = line.slice(7).trim()
      }
      if (line.startsWith('data: ')) {
        data.push(line.slice(6))
      }
    }

    if (!data.length) continue

    try {
      events.push({ event, data: JSON.parse(data.join('\n')) })
    } catch {
      events.push({ event, data: data.join('\n') })
    }
  }

  return { events, rest }
}

async function request(path, options) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `Request failed: ${response.status}`)
  }

  return response.json()
}

function RecommendationCard({ recommendation }) {
  const best = recommendation?.best_option
  const specialty = recommendation?.specialty
  const alternatives = recommendation?.alternatives ?? []

  if (!best || !specialty) return null

  return (
    <aside className="recommendation-card">
      <div>
        <span className="eyebrow">Best economic option</span>
        <h3>{best.hospital_name}</h3>
        <p>{specialty.name}</p>
      </div>

      <div className="money-grid">
        <div>
          <span>Patient pays</span>
          <strong>{money(best.patient_cost_cents)}</strong>
        </div>
        <div>
          <span>Insurance covers</span>
          <strong>{money(best.insurance_covers_cents)}</strong>
        </div>
      </div>

      <div className="alternatives">
        {alternatives.slice(0, 4).map((option) => (
          <div className="alternative" key={option.hospital_id}>
            <span>{option.hospital_name}</span>
            <b>{money(option.patient_cost_cents)}</b>
          </div>
        ))}
      </div>
    </aside>
  )
}

function MessageBubble({ message }) {
  const recommendation = message.metadata?.recommendation

  return (
    <article className={`message ${message.role}`}>
      <div className="message-role">{message.role === 'user' ? 'Patient' : 'Agent'}</div>
      <div className="message-content">{message.content}</div>
      {recommendation ? <RecommendationCard recommendation={recommendation} /> : null}
    </article>
  )
}

function App() {
  const [users, setUsers] = useState([])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [conversations, setConversations] = useState([])
  const [selectedConversationId, setSelectedConversationId] = useState('')
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [progress, setProgress] = useState([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState('')
  const messagesEndRef = useRef(null)

  const selectedUser = useMemo(
    () => users.find((user) => String(user.id) === String(selectedUserId)),
    [selectedUserId, users],
  )

  useEffect(() => {
    async function loadUsers() {
      try {
        const data = await request('/users')
        setUsers(data)
        if (data[0]) setSelectedUserId(String(data[0].id))
      } catch (err) {
        setError(err.message)
      }
    }

    loadUsers()
  }, [])

  useEffect(() => {
    if (!selectedUserId) return

    async function loadConversations() {
      try {
        const data = await request(`/conversations?user_id=${selectedUserId}`)
        setConversations(data)
        setSelectedConversationId(data[0]?.conversation_id ?? '')
        setMessages([])
        setProgress([])
      } catch (err) {
        setError(err.message)
      }
    }

    loadConversations()
  }, [selectedUserId])

  useEffect(() => {
    if (isStreaming) return
    if (!selectedConversationId) {
      setMessages([])
      return
    }

    async function loadMessages() {
      try {
        const data = await request(`/conversations/${selectedConversationId}/messages`)
        setMessages(data)
        setProgress([])
      } catch (err) {
        setError(err.message)
      }
    }

    loadMessages()
  }, [isStreaming, selectedConversationId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, progress])

  async function refreshConversations(conversationId) {
    if (!selectedUserId) return
    const data = await request(`/conversations?user_id=${selectedUserId}`)
    setConversations(data)
    if (conversationId) setSelectedConversationId(conversationId)
  }

  async function createConversation() {
    if (!selectedUserId) return null
    const conversation = await request('/conversations', {
      method: 'POST',
      body: JSON.stringify({ user_id: Number(selectedUserId) }),
    })
    await refreshConversations(conversation.conversation_id)
    setMessages([])
    setProgress([])
    return conversation.conversation_id
  }

  async function sendMessage(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || isStreaming || !selectedUserId) return

    setDraft('')
    setError('')
    setProgress([])
    setIsStreaming(true)

    let conversationId = selectedConversationId
    if (!conversationId) {
      const conversation = await request('/conversations', {
        method: 'POST',
        body: JSON.stringify({ user_id: Number(selectedUserId) }),
      })
      const now = new Date().toISOString()
      conversationId = conversation.conversation_id
      setSelectedConversationId(conversationId)
      setConversations((current) => [
        { ...conversation, created_at: now, updated_at: now, last_message: text },
        ...current,
      ])
    }
    if (!conversationId) {
      setIsStreaming(false)
      return
    }

    setMessages((current) => [
      ...current,
      { role: 'user', content: text, metadata: {}, created_at: new Date().toISOString() },
    ])

    try {
      const response = await fetch(`/conversations/${conversationId}/messages/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })

      if (!response.ok || !response.body) {
        throw new Error(await response.text())
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parsed = parseSse(buffer)
        buffer = parsed.rest

        for (const item of parsed.events) {
          if (item.event === 'status') {
            setProgress((current) => [...current, item.data.message])
          }
          if (item.event === 'error') {
            setError(item.data.message ?? String(item.data))
          }
          if (item.event === 'result') {
            setMessages((current) => [
              ...current,
              {
                role: 'assistant',
                content: item.data.message,
                metadata: { recommendation: item.data.recommendation },
                created_at: new Date().toISOString(),
              },
            ])
          }
        }
      }

      await refreshConversations(conversationId)
    } catch (err) {
      setError(err.message)
    } finally {
      setIsStreaming(false)
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <span className="brand-mark">C</span>
          <div>
            <p>Copay Agent</p>
            <small>Coverage before care</small>
          </div>
        </div>

        <label className="field-label" htmlFor="user-select">Patient</label>
        <select
          id="user-select"
          value={selectedUserId}
          onChange={(event) => setSelectedUserId(event.target.value)}
        >
          {users.map((user) => (
            <option key={user.id} value={user.id}>
              {user.full_name}
            </option>
          ))}
        </select>

        <button className="new-chat" type="button" onClick={createConversation} disabled={!selectedUserId}>
          New conversation
        </button>

        <div className="conversation-list" aria-label="Conversations">
          {conversations.length === 0 ? <p className="empty-sidebar">No conversations yet</p> : null}
          {conversations.map((conversation) => (
            <button
              className={conversation.conversation_id === selectedConversationId ? 'active' : ''}
              key={conversation.conversation_id}
              type="button"
              onClick={() => setSelectedConversationId(conversation.conversation_id)}
            >
              <span>{titleForConversation(conversation)}</span>
              <small>{new Date(conversation.updated_at).toLocaleString()}</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <span className="eyebrow">Selected patient</span>
            <h1>{selectedUser?.full_name ?? 'Select a patient'}</h1>
          </div>
          {selectedUser ? (
            <div className="plan-pill">
              <span>{selectedUser.insurance_company}</span>
              <b>{selectedUser.insurance_plan}</b>
            </div>
          ) : null}
        </header>

        <section className="messages">
          {messages.length === 0 ? (
            <div className="empty-state">
              <span>Start with symptoms</span>
              <h2>Ask where this patient should go and what they will pay.</h2>
              <p>Example: “Tengo dolor en el pecho y palpitaciones desde ayer.”</p>
            </div>
          ) : null}

          {messages.map((message, index) => (
            <MessageBubble key={`${message.role}-${message.created_at}-${index}`} message={message} />
          ))}

          {progress.length ? (
            <div className="progress-box">
              <span>Agent activity</span>
              {progress.map((item, index) => (
                <p key={`${item}-${index}`}>{item}</p>
              ))}
            </div>
          ) : null}

          <div ref={messagesEndRef} />
        </section>

        {error ? <div className="error-banner">{error}</div> : null}

        <form className="composer" onSubmit={sendMessage}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Describe symptoms..."
            rows="2"
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
          />
          <button type="submit" disabled={!draft.trim() || isStreaming || !selectedUserId}>
            {isStreaming ? 'Working' : 'Send'}
          </button>
        </form>
      </section>
    </main>
  )
}

export default App
