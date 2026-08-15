def build_ai_prompt(shift_type, active_requests):
    prompt = f"""
    You are an automated dispatch intelligence engine using past WhatsApp transport records.
    
    DRIVER RULES:
    1. PRIMARY DRIVERS: Use Sridhar (AI882), Kalingarathnam (AI879), Mahendran (AI756), K. Pandi (AI1056), and Senthil (AI933) for core route sweeps.
    2. STAFF DRIVER (Saravanan - AG664): Utilize Saravanan as a staff driver when needed. Prefer assigning him to long-distance locations (Tuas, Jurong Island, Woodlands) or heavy overflow runs. He can do multiple trips if required.
    3. RESIGNED DRIVERS: NEVER assign A. Mani (AI1048) or Ramesh (AG670).
    
    SITE PAIRING MATRIX:
    - Morning Runs: Pair [Wuxi Bio + Jurong Island], [Tengah + Jurong West St 64 + Bulim Square], [Kranji Rd + Woodlands Checkpoint].
    - 7:00 PM Runs: Pair [Jurong West St 64 + Bulim Square], [Kranji Rd + MOE Schools].
    - 9:00 PM / 10:00 PM OT Runs: Pair [Tengah Depot + Woodlands Checkpoint], [Wuxi Bio + Jurong Island].
    
    CURRENT REQUEST DATA:
    {json.dumps(active_requests)}
    
    Generate the complete vehicle assignment schedule for {shift_type}.
    """
    return prompt
