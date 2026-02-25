export default function ModeFields({ config, set }) {
  const mode = config.analysis_mode

  if (mode === 'claude') {
    return (
      <div className="form-grid mt-8">
        <Field
          label="Anthropic API Key"
          value={config.anthropic_api_key}
          onChange={v => set('anthropic_api_key', v)}
          type="password"
          required
          placeholder="Enter your Anthropic API key"
        />
      </div>
    )
  }

  if (mode === 'gemini') {
    const isVertex = config.gemini_use_vertex === 'true'
    return (
      <div className="mt-8">
        <div className="form-grid">
          <Field
            label="Gemini Model"
            value={config.gemini_model}
            onChange={v => set('gemini_model', v)}
            placeholder="Default: gemini-2.0-flash"
          />
          <div className="field">
            <label className="field-label">Backend</label>
            <div className="radio-group">
              <label className="radio-label">
                <input
                  type="radio"
                  name="gemini_backend"
                  checked={!isVertex}
                  onChange={() => set('gemini_use_vertex', 'false')}
                />
                AI Studio
              </label>
              <label className="radio-label">
                <input
                  type="radio"
                  name="gemini_backend"
                  checked={isVertex}
                  onChange={() => set('gemini_use_vertex', 'true')}
                />
                Vertex AI
              </label>
            </div>
          </div>
          {!isVertex && (
            <Field
              label="Google API Key"
              value={config.google_api_key}
              onChange={v => set('google_api_key', v)}
              type="password"
              required
              placeholder="Enter your Google API key"
            />
          )}
          {isVertex && (
            <Field
              label="GCP Project"
              value={config.google_cloud_project}
              onChange={v => set('google_cloud_project', v)}
              required
              placeholder="Enter your GCP project ID"
            />
          )}
          {isVertex && (
            <Field
              label="GCP Region"
              value={config.google_cloud_region}
              onChange={v => set('google_cloud_region', v)}
              placeholder="Default: us-central1"
            />
          )}
        </div>
      </div>
    )
  }

  if (mode === 'openai') {
    return (
      <div className="form-grid mt-8">
        <Field
          label="OpenAI API Key"
          value={config.openai_api_key}
          onChange={v => set('openai_api_key', v)}
          type="password"
          required
          placeholder="Enter your OpenAI API key"
        />
        <Field
          label="Model"
          value={config.openai_model}
          onChange={v => set('openai_model', v)}
          placeholder="Default: gpt-4o-mini"
        />
      </div>
    )
  }

  if (mode === 'azure_openai') {
    return (
      <div className="form-grid mt-8">
        <Field
          label="Azure OpenAI Endpoint"
          value={config.azure_openai_endpoint}
          onChange={v => set('azure_openai_endpoint', v)}
          required
          placeholder="https://my-resource.openai.azure.com/"
        />
        <Field
          label="Azure OpenAI API Key"
          value={config.azure_openai_api_key}
          onChange={v => set('azure_openai_api_key', v)}
          type="password"
          required
          placeholder="Enter your Azure OpenAI API key"
        />
        <Field
          label="Deployment Name"
          value={config.azure_openai_deployment}
          onChange={v => set('azure_openai_deployment', v)}
          required
          placeholder="e.g. gpt-4o"
        />
        <Field
          label="API Version"
          value={config.azure_openai_api_version}
          onChange={v => set('azure_openai_api_version', v)}
          placeholder="Default: 2024-02-01"
        />
      </div>
    )
  }

  if (mode === 'ollama') {
    return (
      <div className="form-grid mt-8">
        <Field
          label="Ollama Model"
          value={config.ollama_model}
          onChange={v => set('ollama_model', v)}
          placeholder="Default: qwen2.5:3b"
        />
        <Field
          label="Ollama URL"
          value={config.ollama_url}
          onChange={v => set('ollama_url', v)}
          placeholder="Default: http://localhost:11434"
        />
      </div>
    )
  }

  // keyword — no extra fields needed
  return (
    <p className="hint mt-8">No API key required. Uses regex keyword rules to classify commits.</p>
  )
}

function Field({ label, value, onChange, type = 'text', required, placeholder }) {
  return (
    <div className="field">
      <label className="field-label">
        {label}
        {required && <span className="required"> *</span>}
      </label>
      <input
        className="field-input"
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={e => onChange(e.target.value)}
      />
    </div>
  )
}
