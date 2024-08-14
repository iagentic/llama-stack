# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.


import logging
import os
import uuid
from typing import AsyncGenerator, Dict

from llama_toolchain.distribution.datatypes import Api, ProviderSpec
from llama_toolchain.inference.api import Inference
from llama_toolchain.inference.api.datatypes import BuiltinTool
from llama_toolchain.memory.api import Memory
from llama_toolchain.safety.api import Safety
from llama_toolchain.agentic_system.api import *  # noqa: F403
from .agent_instance import ChatAgent
from .config import MetaReferenceImplConfig

from llama_toolchain.tools.builtin import (
    BraveSearchTool,
    CodeInterpreterTool,
    PhotogenTool,
    WolframAlphaTool,
)
from llama_toolchain.tools.safety import with_safety

from .agent_instance import AgentInstance


logger = logging.getLogger()
logger.setLevel(logging.INFO)


async def get_provider_impl(
    config: MetaReferenceImplConfig, deps: Dict[Api, ProviderSpec]
):
    assert isinstance(
        config, MetaReferenceImplConfig
    ), f"Unexpected config type: {type(config)}"

    impl = MetaReferenceAgenticSystemImpl(
        config,
        deps[Api.inference],
        deps[Api.safety],
    )
    await impl.initialize()
    return impl


AGENT_INSTANCES_BY_ID = {}


class MetaReferenceAgenticSystemImpl(AgenticSystem):
    def __init__(
        self,
        config: MetaReferenceImplConfig,
        inference_api: Inference,
        safety_api: Safety,
        memory_api: Memory,
    ):
        self.config = config
        self.inference_api = inference_api
        self.safety_api = safety_api
        self.memory_api = memory_api

    async def initialize(self) -> None:
        pass

    async def create_agentic_system(
        self,
        request: AgenticSystemCreateRequest,
    ) -> AgenticSystemCreateResponse:
        system_id = str(uuid.uuid4())

        builtin_tools = []
        custom_tool_definitions = []
        cfg = request.agent_config
        for dfn in cfg.available_tools:
            if isinstance(dfn.tool_name, BuiltinTool):
                if dfn.tool_name == BuiltinTool.wolfram_alpha:
                    key = self.config.wolfram_api_key
                    if not key:
                        raise ValueError("Wolfram API key not defined in config")
                    tool = WolframAlphaTool(key)
                elif dfn.tool_name == BuiltinTool.brave_search:
                    key = self.config.brave_search_api_key
                    if not key:
                        raise ValueError("Brave API key not defined in config")
                    tool = BraveSearchTool(key)
                elif dfn.tool_name == BuiltinTool.code_interpreter:
                    tool = CodeInterpreterTool()
                elif dfn.tool_name == BuiltinTool.photogen:
                    tool = PhotogenTool(
                        dump_dir="/tmp/photogen_dump_" + os.environ["USER"],
                    )
                else:
                    raise ValueError(f"Unknown builtin tool: {dfn.tool_name}")

                builtin_tools.append(
                    with_safety(
                        tool, self.safety_api, dfn.input_shields, dfn.output_shields
                    )
                )
            else:
                custom_tool_definitions.append(dfn)

        AGENT_INSTANCES_BY_ID[system_id] = ChatAgent(
            agent_config=cfg,
            inference_api=self.inference_api,
            safety_api=self.safety_api,
            memory_api=self.memory_api,
            builtin_tools=builtin_tools,
            custom_tool_definitions=custom_tool_definitions,
        )

        return AgenticSystemCreateResponse(
            system_id=system_id,
        )

    async def create_agentic_system_session(
        self,
        request: AgenticSystemSessionCreateRequest,
    ) -> AgenticSystemSessionCreateResponse:
        system_id = request.system_id
        assert system_id in AGENT_INSTANCES_BY_ID, f"System {system_id} not found"
        agent = AGENT_INSTANCES_BY_ID[system_id]

        session = agent.create_session(request.session_name)
        return AgenticSystemSessionCreateResponse(
            session_id=session.session_id,
        )

    async def create_agentic_system_turn(
        self,
        request: AgenticSystemTurnCreateRequest,
    ) -> AsyncGenerator:
        system_id = request.system_id
        assert system_id in AGENT_INSTANCES_BY_ID, f"System {system_id} not found"
        agent = AGENT_INSTANCES_BY_ID[system_id]

        assert (
            request.session_id in agent.sessions
        ), f"Session {request.session_id} not found"
        async for event in agent.create_and_execute_turn(request):
            yield event
