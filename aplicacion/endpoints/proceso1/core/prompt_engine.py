"""
Prompt Engine — Clase base para gestionar generación de prompts.
Proceso 1, módulo core.
"""
import json
from ..prompts.strategic_analysis import generate_strategic_analysis_prompt


class PromptEngine:
    """Motor de generación de prompts para Scienceluxe."""

    def __init__(self, aggregated_data: dict):
        """
        Args:
            aggregated_data: JSON estructurado de content_aggregator.aggregate_sources()
        """
        self.data = aggregated_data

    def generate_strategic_analysis(self) -> dict:
        """
        Genera el prompt de Análisis Estratégico (Proceso 1 final).
        
        Returns:
            dict con keys: prompt_completo, prompt_optimizado
        """
        if isinstance(self.data, list) and len(self.data) > 0:
            main_video_data = self.data[0]
            supplementary_data = self.data[1:]
        else:
            main_video_data = {}
            supplementary_data = []
            
        return generate_strategic_analysis_prompt(main_video_data, supplementary_data)

    def get_all_prompts(self) -> dict:
        """Genera todos los prompts disponibles."""
        return {
            "strategic_analysis": self.generate_strategic_analysis(),
        }
