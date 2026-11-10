"""
Django views for the multicollege chatbot application.
Handles college selection, chat functionality, and college change.
"""

import json
import os
import warnings
from typing import List, Dict
warnings.filterwarnings('ignore', category=FutureWarning)
from django.shortcuts import render, redirect
from django.http import JsonResponse
from .colleges_data import COLLEGES
from .rag import add_to_rag, retrieve_context, ensure_index
from openai import OpenAI
from django.conf import settings


VECTOR_DIR = settings.MEDIA_ROOT
os.makedirs(VECTOR_DIR, exist_ok=True)



VECTOR_DIR = settings.MEDIA_ROOT
os.makedirs(VECTOR_DIR, exist_ok=True)


from openai import OpenAI
from django.conf import settings

# ---------------- MISTRAL INIT ---------------- #
client = OpenAI(
    api_key="9SFbeSxpTtI4tZTCbSnZkPYpRW2Y47n7",
    base_url="https://api.mistral.ai/v1/"
)

def generate_response(prompt):
    """
    Generate AI response using Mistral.
    """
    try:
        response = client.chat.completions.create(
            model="mistral-small-latest",
            messages=[
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.7
        )
        output = response.choices[0].message.content.strip()
        if not output:
            raise ValueError("Empty response from model")
        return output
    except Exception as e:
        print("AI Error:", e)
        return "AI service is temporarily unavailable. Please try again later."

def select_college(request):
    """
    Display college selection page.
    """
    return render(request, "select_college.html", {"colleges": COLLEGES})


def enter_chat(request):
    """
    Handle college selection and start chat session.
    """
    college_id = int(request.POST.get("college_id"))
    request.session["college_id"] = college_id
    request.session["chat_history"] = []
    return redirect("chat")


def chat_page(request):
    """
    Display chat page for the selected college.
    """
    if "college_id" not in request.session:
        return redirect("select")

    college_id = request.session["college_id"]
    college_name = COLLEGES[college_id]["name"]

    return render(request, "chat.html", {
        "college_name": college_name,
        "college_id": college_id
    })


def change_college(request):
    """
    Clear session and redirect to college selection.
    """
    request.session.flush()
    return redirect("select")

import json
import re
import requests
from django.http import JsonResponse
from langdetect import detect
from deep_translator import GoogleTranslator
from bs4 import BeautifulSoup


from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse


# ---------------- TRANSLATION ---------------- #

# Map frontend language codes to translation codes
LANGUAGE_MAP = {
    "en-IN": "en",
    "te-IN": "te",
    "hi-IN": "hi",
    "kn-IN": "kn",
}

def translate_to_english(text: str) -> str:
    if not text:
        return text
    return GoogleTranslator(source="auto", target="en").translate(text)


def translate_back(text: str, lang_code: str) -> str:
    if not text or lang_code == "en":
        return text
    # Convert en-IN to te, hi, kn format
    lang = LANGUAGE_MAP.get(lang_code, "en")
    if lang == "en":
        return text
    return GoogleTranslator(source="auto", target=lang).translate(text)


# ---------------- CLEAN QUERY ---------------- #

def clean_query(question: str) -> str:
    question = question.strip()
    question = re.sub(r"[^\w\s]", "", question)
    return question

def extract_visible_text(url):
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # Remove unwanted tags
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # -------- Visible Text --------
        visible_text = soup.get_text(separator=" ", strip=True)

        # -------- Extract URLs --------
        links_text = []
        for a in soup.find_all("a", href=True):
            link_text = a.get_text(strip=True)
            href = a["href"]

            # Optional: convert relative → absolute URL
            href = requests.compat.urljoin(url, href)

            if link_text:
                links_text.append(f"{link_text} ({href})")
            else:
                links_text.append(href)

        links_combined = "\n".join(links_text)

        # -------- Final Combined Output --------
        final_text = visible_text + "\n\nLINKS:\n" + links_combined
        print("Extracted text length from", url, ":", final_text)
        return final_text

    except Exception as e:
        print("Error fetching:", url, e)
        return ""


def fetch_from_sources(college_id, query):
    college = COLLEGES.get(college_id)
    if not college:
        return ""

    urls = [college["official"], college["wiki"]] + college["aggregators"]

    collected_text = ""

    for url in urls:
        print("Searching:", url)

        page_text = extract_visible_text(url)
        if not page_text:
            continue

        # Smarter matching
        if any(word in page_text.lower() for word in query.lower().split()):
            collected_text += page_text+ "\n\n"
        print("Collected text length so far:",collected_text)
    return collected_text[:5000]

def detect_language_smart(text: str) -> str:
    # Telugu Unicode range
    if re.search(r'[\u0C00-\u0C7F]', text):
        return "te"

    # Hindi (Devanagari)
    if re.search(r'[\u0900-\u097F]', text):
        return "hi"

    # Kannada
    if re.search(r'[\u0C80-\u0CFF]', text):
        return "kn"

    # Fallback to langdetect for English or others
    try:
        lang = detect(text)
        if lang in ["en", "hi", "te", "kn"]:
            return lang
        else:
            return "en"
    except:
        return "en"
 # ================= IMPORTS ================= #
import json
import markdown
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings



# ================= MISTRAL HELPERS ================= #

def is_general_conversation(message):
    """
    Detect if message is casual chat or info query
    """
    try:
        response = client.chat.completions.create(
            model="mistral-small-latest",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Classify the message.\n"
                        "Reply ONLY with:\n"
                        "CHAT -> casual conversation\n"
                        "INFO -> college information query"
                    )
                },
                {"role": "user", "content": message}
            ],
            max_tokens=50,
            temperature=0.3
        )

        label = response.choices[0].message.content.strip().upper()
        return label == "CHAT"

    except Exception as e:
        print("Intent detection error:", e)
        return False


def openai_chat_reply(message, system_prompt=None):
    """
    Direct reply for casual conversations
    """
    if system_prompt is None:
        system_prompt = "You are a friendly AI assistant for a college website. Reply naturally, politely, and briefly."
    
    try:
        response = client.chat.completions.create(
            model="mistral-small-latest",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {"role": "user", "content": message}
            ],
            max_tokens=300,
            temperature=0.7
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        print("Mistral chat error:", e)
        return "Hello! How can I assist you today?"


SYNONYM_MAP = {
    "fee": ["fee structure", "tuition fee", "academic fee", "payment details"],
    "fees": ["fee structure", "tuition fee", "academic fee"],
    "course": ["program", "courses", "academic program", "degree program"],
    "courses": ["programs", "departments", "degree programs"],
    "department": ["dept", "academic department", "branch"],
    "placement": ["placements", "recruitment", "campus placement", "job placement"],
    "admission": ["admissions", "admission process", "eligibility", "application"],
    "faculty": ["staff", "teaching staff", "professors", "lecturers"],
    "hostel": ["accommodation", "student hostel", "residential facility"],
    "library": ["learning resources", "books", "digital library"],
    "transport": ["bus facility", "transportation", "college transport"],
    "academics": ["academic calendar", "academic schedule", "semester dates"],
    "intake": ["admission intake", "seat availability", "capacity"],
    "placement": ["placements", "recruitment", "campus placement", "job placement"],
    "recruitment": ["placements", "campus placement", "job placement"],
    "campus placement": ["placements", "recruitment", "job placement"],
    "job placement": ["placements", "recruitment", "campus placement"],
    'contact': ['contact information', 'contact details', 'phone number', 'email address'],
}

def expand_with_synonyms(query):
    """
    Expand query using predefined academic synonyms.
    """
    query_lower = query.lower()
    expanded_terms = [query]

    for word, synonyms in SYNONYM_MAP.items():
        if word in query_lower:
            expanded_terms.extend(synonyms)

    # remove duplicates
    expanded_terms = list(set(expanded_terms))

    return " ".join(expanded_terms)


def refine_user_question(question):
    """
    Create retrieval-optimized + synonym-expanded query for RAG.
    """
    expanded_query = expand_with_synonyms(question)
    try:
        # ---------- LLM QUERY OPTIMIZATION ----------
        response = client.chat.completions.create(
            model="mistral-small-latest",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Convert the question into a concise academic "
                        "search query for a college information system.\n"
                        "- Extract keywords only.\n"
                        "- Remove conversational words.\n"
                        "- Do NOT answer.\n"
                        "- Return only search keywords."
                    )
                },
                {"role": "user", "content": expanded_query}
            ],
            max_tokens=100,
            temperature=0.3
        )

        optimized_query = response.choices[0].message.content.strip()

    except Exception as e:
        print("Refine error:", e)
        optimized_query = expanded_query

    # ---------- SYNONYM EXPANSION ----------
    

    print("Original:", question)
    print("Optimized:", optimized_query)

    return optimized_query


@csrf_exempt
def chatbot(request):

    if request.method != "POST":
        return JsonResponse({"response": "Invalid request method."})

    try:
        # Handle both request.body and potential request.data
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, AttributeError):
            # Fallback if request.body is empty or invalid
            data = {}
        
        question = data.get("message", "").strip()
        language = data.get("language", "en-IN")
        voice_input = data.get("voice", False)

        # Get short language code for translation
        target_lang = LANGUAGE_MAP.get(language, "en")

        college_id = request.session.get("college_id")
        
        if not question:
            return JsonResponse({"response": "Please enter a valid question.", "voice": voice_input})

        if not college_id:
            return JsonResponse({"response": "College not selected.", "voice": voice_input})

        if not ensure_index(college_id):
            return JsonResponse({
                "response": "Knowledge base is being built... Please wait.",
                "voice": voice_input
            })

        # try:
        #     detected_lang = detect_language_smart(question)
        # except:
        #     detected_lang = "en"

        # print("Detected Language:", detected_lang)

        # ---------- Translate to English ---------- #
        
        english_question = translate_to_english(question)
        

        # ====================================================

        if is_general_conversation(english_question):

            # Add language-specific system prompt
            if target_lang == "te":
                system_prompt = "You are a friendly AI assistant for a college website. Reply naturally, politely, and briefly in Telugu."
            elif target_lang == "hi":
                system_prompt = "You are a friendly AI assistant for a college website. Reply naturally, politely, and briefly in Hindi."
            elif target_lang == "kn":
                system_prompt = "You are a friendly AI assistant for a college website. Reply naturally, politely, and briefly in Kannada."
            else:
                system_prompt = "You are a friendly AI assistant for a college website. Reply naturally, politely, and briefly."

            chat_reply = openai_chat_reply(english_question, system_prompt)

            formatted_answer = markdown.markdown(chat_reply)

            # Translate back to user's language if not English
            if target_lang != "en":
                formatted_answer = translate_back(formatted_answer, language)

            return JsonResponse({
                "response": formatted_answer,
                "voice": voice_input,
                "language": language
            })

      

        cleaned_question = clean_query(english_question)

        refined_question = refine_user_question(cleaned_question)
        print("Refined Question for Retrieval:", refined_question)

        # ---------- Vector Retrieval ---------- #
        context = retrieve_context(college_id, refined_question)

        context = retrieve_context(college_id, refined_question)

# ---------- Website Fallback - Always try to supplement ---------- #
        print("Fetching live website data...")
        website_context = fetch_from_sources(
            college_id,
            cleaned_question
        )
        print("Website Context Length:", website_context)

        # -----------------------------
        # ✅ Add to RAG if new
        # -----------------------------
        if website_context and (not context or website_context[:200] not in context):
            add_to_rag(college_id, website_context)

        # -----------------------------
        # Combine vector and website data
        # -----------------------------
        if website_context:
            if context:
                context = context + "\n\n" + website_context
            else:
                context = website_context

        print("Final Context Length:", len(context) if context else 0)
        # Add language-specific instruction
        if target_lang == "te":
            lang_instruction = "Respond ONLY in Telugu language."
        elif target_lang == "hi":
            lang_instruction = "Respond ONLY in Hindi language."
        elif target_lang == "kn":
            lang_instruction = "Respond ONLY in Kannada language."
        else:
            lang_instruction = "Respond in English."

        prompt = f"""
You are an official AI assistant for a college website.

{lang_instruction}

STRICT RULES:
1. Use ONLY the provided information.
2. Do NOT add or invent details.
3. If unavailable, respond exactly:
   The requested information is not available in the official data.
4. Do NOT use tables.
5. Do NOT repeat the question.
6. Maintain professional academic tone.

FORMAT:
- Clear main heading
- Subheadings
- Bullet points
- No emojis

INFORMATION:
{context}

USER QUESTION:
{question}


Generate a clean structured answer.
"""

        answer = generate_response(prompt)
        print(answer)
        formatted_answer = markdown.markdown(answer)

        # Translate back to user's language if not English
        if target_lang != "en":
            formatted_answer = translate_back(formatted_answer, language)

        return JsonResponse({
            "response": formatted_answer,
            "voice": voice_input,
            "language": language
        })

    except Exception as e:
        print("Chatbot Error:", str(e))
        return JsonResponse({
            "response": "Something went wrong. Please try again.",
            "voice": voice_input
        })
