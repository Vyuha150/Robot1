"""
bonbon_perception_ai.langchain_tools
=====================================
Optional LangChain-powered tools.  This subpackage is imported lazily; the
absence of the ``langchain`` library does not break the default rule-based
pipeline.

Exposed when langchain is installed:
  build_intent_chain     — build a ChatOpenAI intent-classification chain
  classify_with_chain    — run text through the chain, returns (class, conf)
  build_scene_chain      — build a chain for natural-language scene summaries
  describe_scene         — run a SceneSnapshot through the scene chain
"""

# Intentionally thin — do NOT import langchain at module load time.
# Consumers must import from the submodules directly:
#
#   from bonbon_perception_ai.langchain_tools.intent_chain import (
#       build_intent_chain, classify_with_chain,
#   )
#   from bonbon_perception_ai.langchain_tools.scene_describer import (
#       build_scene_chain, describe_scene,
#   )
