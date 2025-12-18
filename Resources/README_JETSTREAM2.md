# Jetstream2 Integration

## Overview

DeveloperAgent now supports free, high-performance models from Jetstream2's inference service, providing access to state-of-the-art reasoning models at no cost.

## Available Jetstream2 Models

### DeepSeek R1 (671B parameters)
- **Best for**: Complex Slicer workflows, detailed code generation
- **Performance**: 36 tokens/second
- **Capabilities**: Chain-of-thought reasoning, comparable to OpenAI o1/o3
- **Endpoint**: `https://llm.jetstream-cloud.org/sglang/v1`
- **Hardware**: 8x AMD MI300X GPUs (1536 GB VRAM total)

### gpt-oss-120b (120B parameters)
- **Best for**: Fast reasoning tasks
- **Performance**: 180 tokens/second (fastest)
- **Capabilities**: Configurable reasoning effort (low/medium/high)
- **Endpoint**: `https://llm.jetstream-cloud.org/gpt-oss-120b/v1`
- **Hardware**: 2x NVIDIA H100 GPUs

### Llama 4 Scout (multimodal)
- **Best for**: General-purpose tasks, conversational refinement
- **Performance**: 83 tokens/second
- **Capabilities**: Text + vision, instruct-tuned for conversations
- **Endpoint**: `https://llm.jetstream-cloud.org/llama-4-scout/v1`
- **Hardware**: 2x NVIDIA H100 GPUs

## Authentication

**Jetstream2 models require NO API key** when accessed from:
- Jetstream2 instances
- IU Research Cloud instances
- Any computer with tunneled connection through a Jetstream2 instance

The module automatically uses `api_key="empty"` for Jetstream2 models.

## Network Access Requirements

### From Jetstream2 Instance (Direct Access)
No additional configuration needed - the module will work immediately.

### From External Computer (Tunneling Required)

#### Option 1: sshuttle (Recommended)
```bash
# Install sshuttle
brew install sshuttle  # macOS
sudo apt install sshuttle  # Ubuntu

# Create tunnel through your Jetstream2 instance
sshuttle -r exouser@YOUR-INSTANCE-IP 149.165.156.93/32
```

#### Option 2: SSH Port Forwarding
```bash
# Add to /etc/hosts (requires sudo)
127.0.0.1 llm.jetstream-cloud.org

# Create SSH tunnel
ssh -L 1234:149.165.156.93:443 exouser@YOUR-INSTANCE-IP

# Then modify endpoints in DeveloperAgent.py to use :1234 port
```

## Model Comparison

| Model | Params | Speed | Best For | GitHub Models Equivalent |
|-------|--------|-------|----------|-------------------------|
| DeepSeek R1 | 671B | Slow | Complex reasoning | Better than GPT-4o |
| gpt-oss-120b | 120B | Fast | Quick reasoning | Similar to GPT-4 Turbo |
| Llama 4 Scout | - | Medium | General tasks | Similar to Llama 3.3 70B |
| GPT-4o | ~200B | Fast | General (rate limited) | - |

## Benefits

1. **No Cost**: Unlimited use with ACCESS account (no GitHub rate limits)
2. **Higher Quality**: DeepSeek R1 rivals OpenAI o1 for reasoning tasks
3. **Data Sovereignty**: US-based infrastructure (IU Bloomington Data Center)
4. **Privacy**: No data mining, no training on your prompts
5. **No SU Charges**: Doesn't consume Jetstream2 Service Units

## Recommendations

### For This Project (Slicer Code Generation)

- **Start with**: DeepSeek R1 (best for generating correct, complete workflows)
- **If too slow**: Switch to gpt-oss-120b (3x faster reasoning)
- **Fallback**: GPT-4o (if not on Jetstream2 network)

### When to Use Each Model

- **DeepSeek R1**: First-time code generation, complex segmentation workflows, debugging hard errors
- **gpt-oss-120b**: Iterative refinements, quick fixes, testing RAG retrieval
- **Llama 4 Scout**: Simple scripts, conversational back-and-forth
- **GPT-4o**: When off Jetstream2 network or need faster responses than DeepSeek

## Integration Details

The module automatically detects Jetstream2 models by their model ID:
- `DeepSeek-R1`
- `gpt-oss-120b`
- `llama-4-scout`

When detected, it:
1. Uses the appropriate Jetstream2 endpoint
2. Sets `api_key="empty"` (no authentication required)
3. Routes requests through OpenAI-compatible API

## Limitations

1. **Network Access**: Must be on Jetstream2/IU network or use tunnel
2. **No Web Search**: Web search feature (DuckDuckGo integration) not available via API
3. **Reasoning Output**: DeepSeek R1 includes verbose "thinking" in responses (not shown to user)
4. **Concurrent Requests**: Shared service may slow during heavy load

## Getting ACCESS Account

If you don't have an ACCESS account:
1. Sign up at: https://identity.access-ci.org/new-user
2. Create Jetstream2 allocation (trial or research)
3. Launch instance and access inference service

## Documentation References

- Jetstream2 Inference Service: https://docs.jetstream-cloud.org/inference-service/overview/
- API Access: https://docs.jetstream-cloud.org/inference-service/api/
- API Examples: https://docs.jetstream-cloud.org/inference-service/api-examples/
- Community Chat: https://matrix.to/#/#js2-inference-service:matrix.org

## Testing

To verify Jetstream2 integration:

1. Select a Jetstream2 model from the dropdown in DeveloperAgent UI
2. Generate a script (e.g., "Create a script that segments a volume using threshold")
3. Check Slicer Python console for confirmation:
   - Should show: `Using AI model: DeepSeek-R1` (or other Jetstream2 model)
   - Should NOT show authentication errors
   - Generated code should include correct API patterns from RAG/curated examples

## Future Enhancements

- **Auto-detect network**: Fall back to GitHub Models if Jetstream2 unreachable
- **Reasoning effort control**: Add UI toggle for gpt-oss-120b's low/medium/high reasoning
- **Model recommendations**: Suggest model based on request complexity
- **Performance metrics**: Track generation time and quality per model
