"""Gemini Pro 1.5 Evaluator"""

import requests
import json
from tqdm import tqdm
import random
import time
import pdb
from utils import encode_image_PIL
from args import api_price



class GeminiEvaluator:
    def __init__(self, api_key, model='gemini-1.5-pro-latest', api_url=None,use_client=False):
        self.use_client = use_client
        self.api_key = api_key
        self.api_url = api_url
        if self.use_client:
            import google.generativeai as genai
            genai.configure(api_key=api_key, transport='rest')
            block_type = "BLOCK_ONLY_HIGH"
            self.safety_settings = [{
                "category": "HARM_CATEGORY_DANGEROUS",
                "threshold": block_type,
            }, {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": block_type,
            }, {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": block_type,
            }, {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": block_type,
            }, {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": block_type,
            }, ]
            
            self.client = genai.GenerativeModel(model_name=model, safety_settings=self.safety_settings)
        else:
            self.header = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            self.post_dict = {
                "model": model,
                "system": None,
                "messages": None
            }
        self.model = model
        self.tokens = {
            "prompt_tokens": 0,
            "completion_tokens": 0
        }
        self.tokens_this_run = {
            "prompt_tokens": 0,
            "completion_tokens": 0
        }
        self.price = api_price.get(model, [0.00125, 0.005])


    def prepare_inputs(self, question):
        prompt = question["prompted_system_content"].strip() + "\n" + question["prompted_content"].strip()
        content = [prompt,]

        image_list = question.get("image_list")
        if image_list:
            for image_path in image_list:
                image = encode_image_PIL(image_path)  # max_size = 512
                content.append(image)
        return content

    def generate_response(self, question):
        content = self.prepare_inputs(question)
        message = None
        response = ""
        i = 0
        MAX_RETRY = 100
        while i < MAX_RETRY:
            try:
                if len(content) > 1:
                    response_ = self.model_with_vision.generate_content(content)
                    message = [content[0], ]
                    for i in range(len(content) - 1):
                        message.append(str(content[i+1]))
                else:
                    response_ = self.model_without_vision.generate_content(content)
                    message = content
                response = response_.text
            except KeyboardInterrupt:
                raise Exception("Terminated by user.")
            except Exception as e:
                print(e)
                i += 1
                time.sleep(1 + i / 10)
                if i == 1 or i % 10 == 0:
                    if str(e).endswith("if the prompt was blocked.") or str(e).endswith("lookup instead."):
                        response = ""
                        feedback = str(response_.prompt_feedback)
                        return response, message, feedback
                    print(f"Retry {i} times...")
            else:
                break
        if i >= MAX_RETRY:
            raise Exception("Failed to generate response.")
        return response, message, None

    def generate_answer(self, question):
        response, message, feedback = self.generate_response(question)
        question["input_message"] = message
        question["prediction"] = response
        if feedback:
            question["feedback"] = feedback
        question.pop("prompted_content")
        question.pop("prompted_system_content")
        return question
