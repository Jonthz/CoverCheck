import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'

const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
const tabs = [
  { id: 'seguro', label: 'Mi seguro' },
  { id: 'hospitales', label: 'Hospitales' },
  { id: 'especialidades', label: 'Especialidades' },
  { id: 'cobertura', label: 'Cobertura' },
]

function money(cents) {
  return currency.format((cents ?? 0) / 100)
}

function titleForConversation(conversation) {
  return conversation?.last_message || `Conversación ${conversation?.conversation_id?.slice(0, 8) ?? ''}`
}

function parseSse(buffer) {
  const events = []
  const blocks = buffer.split('\n\n')
  const rest = blocks.pop() ?? ''
  for (const block of blocks) {
    let event = 'message'
    const data = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7).trim()
      if (line.startsWith('data: ')) data.push(line.slice(6))
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
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!response.ok) throw new Error((await response.text()) || `Error ${response.status}`)
  return response.json()
}

function RecommendationCard({ recommendation }) {
  const best = recommendation?.best_option
  const specialty = recommendation?.specialty
  const options = recommendation?.all_options ?? recommendation?.alternatives ?? []
  if (!best || !specialty) return null

  return (
    <aside className="recommendation-card">
      <div>
        <span className="eyebrow">Mejor opción económica</span>
        <h3>{best.hospital_name}</h3>
        <p>{specialty.name}</p>
        <p className="reason-text">{recommendation.selection_reason}</p>
      </div>

      <div className="money-grid">
        <div><span>Paciente paga</span><strong>{money(best.patient_cost_cents)}</strong></div>
        <div><span>Seguro cubre</span><strong>{money(best.insurance_covers_cents)}</strong></div>
      </div>

      <div className="hospital-comparison">
        {options.map((option) => (
          <div className="comparison-row" key={option.hospital_id}>
            <div>
              <b>{option.hospital_name}</b>
              <span>{option.city} · {option.in_network ? 'En red' : 'Fuera de red'} · {option.network_tier}</span>
              <small>{option.reason}</small>
            </div>
            <div className="comparison-money">
              <strong>{money(option.patient_cost_cents)}</strong>
              <span>Lista {money(option.list_price_cents)}</span>
              <span>Negociado {money(option.negotiated_price_cents)}</span>
              <span>Cobertura {option.coverage_percent}%</span>
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}

function MessageBubble({ message }) {
  return (
    <article className={`message ${message.role}`}>
      <div className="message-role">{message.role === 'user' ? 'Paciente' : 'Agente'}</div>
      <div className="message-content">{message.content}</div>
      {message.metadata?.recommendation ? <RecommendationCard recommendation={message.metadata.recommendation} /> : null}
    </article>
  )
}

function PatientSelection({ users, onSelect }) {
  return (
    <main className="patient-screen">
      <section className="patient-hero">
        <span className="eyebrow">Estimador agéntico</span>
        <h1>Selecciona un paciente</h1>
        <p>Elige un perfil para revisar su seguro, red hospitalaria y conversaciones.</p>
      </section>
      <section className="patient-grid">
        {users.map((user) => (
          <button className="patient-card" key={user.id} type="button" onClick={() => onSelect(String(user.id))}>
            <span>{user.city}</span>
            <h2>{user.full_name}</h2>
            <p>{user.age} años</p>
            <b>{user.insurance_company}</b>
            <small>{user.insurance_plan}</small>
          </button>
        ))}
      </section>
    </main>
  )
}

function ReferencePanel({ activeTab, selectedUser, data }) {
  if (!selectedUser) return null

  if (activeTab === 'seguro') {
    const insurance = data.insurance
    return (
      <section className="reference-panel">
        <h2>Mi seguro</h2>
        <div className="metric-grid">
          <div><span>Aseguradora</span><b>{insurance?.insurance_company}</b></div>
          <div><span>Plan</span><b>{insurance?.insurance_plan}</b></div>
          <div><span>Deducible anual</span><b>{money(insurance?.annual_deductible_cents)}</b></div>
          <div><span>Coaseguro</span><b>{insurance?.coinsurance_percent}%</b></div>
          <div><span>Cobertura máxima</span><b>{money(insurance?.max_coverage_cents)}</b></div>
        </div>
      </section>
    )
  }

  if (activeTab === 'hospitales') {
    return (
      <section className="reference-panel"><h2>Hospitales disponibles</h2><div className="data-list">
        {(data.hospitals ?? []).map((hospital) => <div key={hospital.id}><b>{hospital.name}</b><span>{hospital.city} · {hospital.network_tier}</span></div>)}
      </div></section>
    )
  }

  if (activeTab === 'especialidades') {
    return (
      <section className="reference-panel"><h2>Especialidades</h2><div className="data-list">
        {(data.specialties ?? []).map((specialty) => <div key={specialty.id}><b>{specialty.name}</b><span>{specialty.description}</span></div>)}
      </div></section>
    )
  }

  return (
    <section className="reference-panel">
      <h2>Cobertura por hospital y especialidad</h2>
      <div className="coverage-table">
        {(data.coverage ?? []).map((row) => (
          <div key={`${row.hospital_id}-${row.specialty_id}`}>
            <b>{row.hospital_name}</b>
            <span>{row.specialty_name}</span>
            <span>{row.in_network ? 'En red' : 'Fuera de red'}</span>
            <span>Paciente aprox.: {row.in_network ? money(Math.max(row.fixed_copay_cents ?? 0, row.negotiated_price_cents - Math.floor(row.negotiated_price_cents * row.coverage_percent / 100))) : money(row.list_price_cents)}</span>
          </div>
        ))}
      </div>
    </section>
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
  const [activeTab, setActiveTab] = useState('seguro')
  const [referenceData, setReferenceData] = useState({})
  const messagesEndRef = useRef(null)

  const selectedUser = useMemo(() => users.find((user) => String(user.id) === String(selectedUserId)), [selectedUserId, users])

  useEffect(() => {
    request('/users').then(setUsers).catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!selectedUserId) return
    async function loadForUser() {
      try {
        const [conversationData, insurance, hospitals, specialties, coverage] = await Promise.all([
          request(`/conversations?user_id=${selectedUserId}`),
          request(`/users/${selectedUserId}/insurance`),
          request('/hospitals'),
          request('/specialties'),
          request(`/users/${selectedUserId}/coverage`),
        ])
        setConversations(conversationData)
        setSelectedConversationId(conversationData[0]?.conversation_id ?? '')
        setMessages([])
        setProgress([])
        setReferenceData({ insurance, hospitals, specialties, coverage })
      } catch (err) {
        setError(err.message)
      }
    }
    loadForUser()
  }, [selectedUserId])

  useEffect(() => {
    if (isStreaming) return
    if (!selectedConversationId) return
    request(`/conversations/${selectedConversationId}/messages`)
      .then((data) => { setMessages(data); setProgress([]) })
      .catch((err) => setError(err.message))
  }, [isStreaming, selectedConversationId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, progress])

  async function refreshConversations(conversationId) {
    const data = await request(`/conversations?user_id=${selectedUserId}`)
    setConversations(data)
    if (conversationId) setSelectedConversationId(conversationId)
  }

  async function createConversation() {
    const conversation = await request('/conversations', { method: 'POST', body: JSON.stringify({ user_id: Number(selectedUserId) }) })
    await refreshConversations(conversation.conversation_id)
    setMessages([])
    setProgress([])
    return conversation.conversation_id
  }

  function changePatient() {
    setSelectedUserId('')
    setSelectedConversationId('')
    setConversations([])
    setMessages([])
    setProgress([])
    setReferenceData({})
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
    try {
      if (!conversationId) conversationId = await createConversation()
      setMessages((current) => [...current, { role: 'user', content: text, metadata: {}, created_at: new Date().toISOString() }])
      const response = await fetch(`/conversations/${conversationId}/messages/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: text }),
      })
      if (!response.ok || !response.body) throw new Error(await response.text())

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
          if (item.event === 'status') setProgress((current) => [...current, item.data.message])
          if (item.event === 'error') setError(item.data.message ?? String(item.data))
          if (item.event === 'result') {
            setMessages((current) => [...current, {
              role: 'assistant', content: item.data.message,
              metadata: { recommendation: item.data.recommendation }, created_at: new Date().toISOString(),
            }])
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

  if (!selectedUserId) return <PatientSelection users={users} onSelect={setSelectedUserId} />

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand-block"><span className="brand-mark">C</span><div><p>Agente de Copago</p><small>{selectedUser?.full_name}</small></div></div>
        <button className="new-chat" type="button" onClick={createConversation}>Nueva conversación</button>
        <button className="switch-user" type="button" onClick={changePatient}>Cambiar paciente</button>
        <div className="conversation-list" aria-label="Conversaciones">
          {conversations.length === 0 ? <p className="empty-sidebar">Aún no hay conversaciones</p> : null}
          {conversations.map((conversation) => (
            <button className={conversation.conversation_id === selectedConversationId ? 'active' : ''} key={conversation.conversation_id} type="button" onClick={() => setSelectedConversationId(conversation.conversation_id)}>
              <span>{titleForConversation(conversation)}</span>
              <small>{new Date(conversation.updated_at).toLocaleString()}</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="chat-panel">
        <header className="chat-header">
          <div><span className="eyebrow">Paciente seleccionado</span><h1>{selectedUser?.full_name}</h1></div>
          <div className="plan-pill"><span>{selectedUser?.insurance_company}</span><b>{selectedUser?.insurance_plan}</b></div>
        </header>

        <nav className="data-tabs">
          {tabs.map((tab) => <button className={activeTab === tab.id ? 'active' : ''} key={tab.id} type="button" onClick={() => setActiveTab(tab.id)}>{tab.label}</button>)}
        </nav>
        <ReferencePanel activeTab={activeTab} selectedUser={selectedUser} data={referenceData} />

        <section className="messages">
          {messages.length === 0 ? <div className="empty-state"><span>Empieza con los síntomas</span><h2>Pregunta a qué especialidad debe ir y cuánto pagará.</h2><p>Ejemplo: “Tengo dolor en el pecho y palpitaciones desde ayer.”</p></div> : null}
          {messages.map((message, index) => <MessageBubble key={`${message.role}-${message.created_at}-${index}`} message={message} />)}
          {progress.length ? <div className="progress-box"><span>Actividad del agente</span>{progress.map((item, index) => <p key={`${item}-${index}`}>{item}</p>)}</div> : null}
          <div ref={messagesEndRef} />
        </section>

        {error ? <div className="error-banner">{error}</div> : null}
        <form className="composer" onSubmit={sendMessage}>
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Describe los síntomas..." rows="2" onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit() } }} />
          <button type="submit" disabled={!draft.trim() || isStreaming}>{isStreaming ? 'Procesando' : 'Enviar'}</button>
        </form>
      </section>
    </main>
  )
}

export default App
