import importlib
import os
import sys
from types import SimpleNamespace


sys.path.append(os.path.dirname(os.path.dirname(__file__)))


def test_bedrock_kb_retrieval_uses_bedrock_region(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    monkeypatch.setenv("BEDROCK_AWS_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_KB_ID", "GH3FUCYVOJ")

    client_calls = []

    class FakeBedrockAgentRuntimeClient:
        def retrieve(self, **kwargs):
            return {
                "retrievalResults": [
                    {"content": {"text": "INC-4 from Bedrock Knowledge Base"}}
                ]
            }

    class FakeBedrockRuntimeClient:
        pass

    def fake_boto3_client(service_name, region_name=None):
        client_calls.append((service_name, region_name))
        if service_name == "bedrock-agent-runtime":
            return FakeBedrockAgentRuntimeClient()
        if service_name == "bedrock-runtime":
            return FakeBedrockRuntimeClient()
        raise AssertionError(f"unexpected boto3 client: {service_name}")

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=fake_boto3_client))

    import config
    import llm_diagnostician

    importlib.reload(config)
    importlib.reload(llm_diagnostician)

    diagnostician = llm_diagnostician.LLMDiagnostician()
    retrieved = diagnostician.retrieve_relevant_playbooks_from_aws("bedrock 429", k=1)

    assert retrieved == "INC-4 from Bedrock Knowledge Base"
    assert ("bedrock-runtime", "us-east-1") in client_calls
    assert ("bedrock-agent-runtime", "us-east-1") in client_calls
