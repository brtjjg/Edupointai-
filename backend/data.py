PAYMENT_PLANS = {
    "standard": {
        "amount": 100,
        "name": "Single Calculation",
        "features": ["1 Cluster Calculation", "PDF Report via Email"]
    }
}

W = {'A':12,'A-':11,'B+':10,'B':9,'B-':8,'C+':7,'C':6,'C-':5,'D+':4,'D':3,'D-':2,'E':1}
G = ['A','A-','B+','B','B-','C+','C','C-','D+','D','D-','E']
S = ['MAT A(121)','ENG(101)','KIS(102)','BIO(231)','CHE(233)','PHY(232)','GEO(312)',
     'HIS(311)','CRE(313)','BUS(565)','AGR(443)','CMP(451)','FRE(501)','MUC(511)',
     'HSC(441)','ACC(561)']
BEST = 84.0
MAX = 48.0

P = [
{"n":"Medicine & Surgery (MBChB)","u":"UNIVERSITY OF NAIROBI","c":45.584,"y":"6","s":"150K-500K+","i":"🏥"},
{"n":"Medicine & Surgery (MBChB)","u":"KENYATTA UNIVERSITY","c":45.433,"y":"6","s":"150K-500K+","i":"🏥"},
{"n":"Medicine & Surgery (MBChB)","u":"MOI UNIVERSITY","c":45.087,"y":"6","s":"150K-500K+","i":"🏥"},
{"n":"Medicine & Surgery (MBChB)","u":"JKUAT","c":45.048,"y":"6","s":"150K-500K+","i":"🏥"},
{"n":"Medicine & Surgery (MBChB)","u":"EGERTON UNIVERSITY","c":44.563,"y":"6","s":"150K-500K+","i":"🏥"},
{"n":"Dental Surgery","u":"UNIVERSITY OF NAIROBI","c":44.750,"y":"5","s":"120K-400K","i":"🦷"},
{"n":"Pharmacy","u":"UNIVERSITY OF NAIROBI","c":44.452,"y":"5","s":"80K-250K","i":"💊"},
{"n":"Pharmacy","u":"KENYATTA UNIVERSITY","c":44.010,"y":"5","s":"80K-250K","i":"💊"},
{"n":"Pharmacy","u":"JKUAT","c":43.872,"y":"5","s":"80K-250K","i":"💊"},
{"n":"Pharmacy","u":"KISII UNIVERSITY","c":43.111,"y":"5","s":"80K-250K","i":"💊"},
{"n":"Nursing","u":"UNIVERSITY OF NAIROBI","c":43.676,"y":"4","s":"50K-150K","i":"🩺"},
{"n":"Nursing","u":"MASENO UNIVERSITY","c":42.529,"y":"4","s":"50K-150K","i":"🩺"},
{"n":"Nursing","u":"MOI UNIVERSITY","c":42.390,"y":"4","s":"50K-150K","i":"🩺"},
{"n":"Nursing","u":"EGERTON UNIVERSITY","c":42.166,"y":"4","s":"50K-150K","i":"🩺"},
{"n":"Nursing","u":"KISII UNIVERSITY","c":42.080,"y":"4","s":"50K-150K","i":"🩺"},
{"n":"Clinical Medicine","u":"JKUAT","c":42.847,"y":"4","s":"60K-180K","i":"🩻"},
{"n":"Medical Lab Science","u":"UNIVERSITY OF NAIROBI","c":41.309,"y":"4","s":"40K-120K","i":"🔬"},
{"n":"Radiography","u":"JKUAT","c":43.325,"y":"4","s":"70K-200K","i":"🩻"},
{"n":"Physiotherapy","u":"JKUAT","c":38.224,"y":"4","s":"50K-150K","i":"💪"},
{"n":"Public Health","u":"JKUAT","c":37.245,"y":"4","s":"45K-130K","i":"🏘️"},
{"n":"Computer Science","u":"UNIVERSITY OF NAIROBI","c":44.825,"y":"4","s":"80K-500K+","i":"💻"},
{"n":"Computer Science","u":"JKUAT","c":44.101,"y":"4","s":"80K-500K+","i":"💻"},
{"n":"Computer Science","u":"KENYATTA UNIVERSITY","c":43.497,"y":"4","s":"70K-400K","i":"💻"},
{"n":"Computer Science","u":"MULTIMEDIA UNIVERSITY","c":41.039,"y":"4","s":"60K-350K","i":"💻"},
{"n":"Computer Science","u":"DEDAN KIMATHI UNIVERSITY","c":39.746,"y":"4","s":"60K-350K","i":"💻"},
{"n":"Computer Science","u":"MASENO UNIVERSITY","c":38.155,"y":"4","s":"60K-350K","i":"💻"},
{"n":"Computer Science","u":"MASINDE MULIRO UNIVERSITY","c":36.480,"y":"4","s":"50K-300K","i":"💻"},
{"n":"Software Engineering","u":"MULTIMEDIA UNIVERSITY","c":41.368,"y":"4","s":"80K-450K","i":"🖥️"},
{"n":"Information Technology","u":"JKUAT","c":39.851,"y":"4","s":"50K-250K","i":"🌐"},
{"n":"Information Technology","u":"MASENO UNIVERSITY","c":31.702,"y":"4","s":"40K-200K","i":"🌐"},
{"n":"Civil Engineering","u":"UNIVERSITY OF NAIROBI","c":43.463,"y":"5","s":"70K-300K","i":"🏗️"},
{"n":"Civil Engineering","u":"JKUAT","c":42.618,"y":"5","s":"70K-300K","i":"🏗️"},
{"n":"Civil Engineering","u":"KENYATTA UNIVERSITY","c":42.574,"y":"5","s":"60K-250K","i":"🏗️"},
{"n":"Electrical & Electronic Eng.","u":"UNIVERSITY OF NAIROBI","c":43.003,"y":"5","s":"70K-350K","i":"⚡"},
{"n":"Electrical & Electronic Eng.","u":"JKUAT","c":42.434,"y":"5","s":"70K-350K","i":"⚡"},
{"n":"Mechanical Engineering","u":"UNIVERSITY OF NAIROBI","c":41.835,"y":"5","s":"60K-300K","i":"⚙️"},
{"n":"Mechanical Engineering","u":"JKUAT","c":41.450,"y":"5","s":"60K-300K","i":"⚙️"},
{"n":"Mechatronic Engineering","u":"JKUAT","c":43.232,"y":"5","s":"80K-400K","i":"🤖"},
{"n":"Architectural Studies","u":"UNIVERSITY OF NAIROBI","c":42.990,"y":"6","s":"60K-300K","i":"🏛️"},
{"n":"Marine Engineering","u":"JKUAT","c":35.669,"y":"5","s":"80K-400K","i":"🚢"},
{"n":"Actuarial Science","u":"UNIVERSITY OF NAIROBI","c":39.531,"y":"4","s":"100K-500K+","i":"📈"},
{"n":"Actuarial Science","u":"KENYATTA UNIVERSITY","c":34.474,"y":"4","s":"80K-400K","i":"📈"},
{"n":"Actuarial Science","u":"JKUAT","c":34.347,"y":"4","s":"80K-400K","i":"📈"},
{"n":"Statistics","u":"UNIVERSITY OF NAIROBI","c":35.192,"y":"4","s":"60K-300K","i":"📉"},
{"n":"Bachelor of Commerce","u":"UNIVERSITY OF NAIROBI","c":34.426,"y":"4","s":"50K-250K","i":"💼"},
{"n":"Bachelor of Commerce","u":"KENYATTA UNIVERSITY","c":32.613,"y":"4","s":"45K-200K","i":"💼"},
{"n":"Economics","u":"UNIVERSITY OF NAIROBI","c":26.096,"y":"4","s":"50K-250K","i":"💰"},
{"n":"Business Management","u":"KISII UNIVERSITY","c":21.375,"y":"4","s":"35K-200K","i":"📋"},
{"n":"Education (Science)","u":"KENYATTA UNIVERSITY","c":37.208,"y":"4","s":"35K-120K","i":"📚"},
{"n":"Education (Science)","u":"UNIVERSITY OF NAIROBI","c":36.127,"y":"4","s":"35K-120K","i":"📚"},
{"n":"Education (Arts)","u":"KENYATTA UNIVERSITY","c":33.556,"y":"4","s":"30K-100K","i":"📖"},
{"n":"Education (Arts)","u":"UNIVERSITY OF NAIROBI","c":32.421,"y":"4","s":"30K-100K","i":"📖"},
{"n":"Education (Arts)","u":"EGERTON UNIVERSITY","c":32.306,"y":"4","s":"30K-100K","i":"📖"},
{"n":"Bachelor of Arts","u":"UNIVERSITY OF NAIROBI","c":23.248,"y":"4","s":"30K-150K","i":"🎭"},
{"n":"Bachelor of Arts","u":"KENYATTA UNIVERSITY","c":24.057,"y":"4","s":"30K-150K","i":"🎭"},
{"n":"Bachelor of Arts","u":"EGERTON UNIVERSITY","c":24.188,"y":"4","s":"30K-150K","i":"🎭"},
{"n":"Bachelor of Arts","u":"MOI UNIVERSITY","c":23.716,"y":"4","s":"30K-150K","i":"🎭"},
{"n":"Bachelor of Arts (With IT)","u":"MASENO UNIVERSITY","c":22.721,"y":"4","s":"35K-180K","i":"🎭"},
{"n":"Agriculture","u":"EGERTON UNIVERSITY","c":15.864,"y":"4","s":"30K-150K","i":"🌾"},
{"n":"Agriculture","u":"JKUAT","c":29.064,"y":"4","s":"35K-180K","i":"🌾"},
{"n":"Veterinary Medicine","u":"UNIVERSITY OF NAIROBI","c":37.747,"y":"5","s":"60K-300K","i":"🐄"},
{"n":"Bachelor of Laws (LLB)","u":"UNIVERSITY OF NAIROBI","c":42.500,"y":"4","s":"80K-500K+","i":"⚖️"},
{"n":"Bachelor of Laws (LLB)","u":"KENYATTA UNIVERSITY","c":42.000,"y":"4","s":"70K-400K","i":"⚖️"},
    # --- NEW EXPANSION: 120+ COURSES ---

    # 1. HEALTH SCIENCES
    {"n":"Dental Surgery","u":"MOI UNIVERSITY","c":44.120,"y":"5","s":"150K-400K","i":"🦷"},
    {"n":"Pharmacy","u":"MOI UNIVERSITY","c":42.500,"y":"5","s":"100K-300K","i":"💊"},
    {"n":"Nursing","u":"KABARAK UNIVERSITY","c":40.100,"y":"4","s":"60K-150K","i":"🩺"},
    {"n":"Clinical Medicine","u":"MOI UNIVERSITY","c":41.800,"y":"4","s":"80K-200K","i":"🩻"},
    {"n":"Medical Lab Science","u":"KENYATTA UNIVERSITY","c":40.500,"y":"4","s":"60K-150K","i":"🔬"},
    {"n":"Public Health","u":"KENYATTA UNIVERSITY","c":35.400,"y":"4","s":"50K-120K","i":"🏘️"},
    {"n":"Environmental Health","u":"MASENO UNIVERSITY","c":30.200,"y":"4","s":"40K-100K","i":"🌿"},
    {"n":"Health Records & IT","u":"KENYATTA UNIVERSITY","c":33.100,"y":"4","s":"50K-120K","i":"📄"},
    {"n":"Radiography","u":"UNIVERSITY OF NAIROBI","c":43.100,"y":"4","s":"80K-200K","i":"🩻"},
    {"n":"Physiotherapy","u":"MOI UNIVERSITY","c":39.500,"y":"4","s":"60K-150K","i":"💪"},

    # 2. ENGINEERING & TECHNOLOGY
    {"n":"Aerospace Engineering","u":"UNIVERSITY OF NAIROBI","c":44.500,"y":"5","s":"150K-500K","i":"✈️"},
    {"n":"Biomedical Engineering","u":"KENYATTA UNIVERSITY","c":40.200,"y":"5","s":"100K-300K","i":"🦾"},
    {"n":"Chemical Engineering","u":"UNIVERSITY OF NAIROBI","c":43.800,"y":"5","s":"100K-400K","i":"🧪"},
    {"n":"Petroleum Engineering","u":"UNIVERSITY OF NAIROBI","c":42.500,"y":"5","s":"200K-600K","i":"🛢️"},
    {"n":"Telecommunication Engineering","u":"JKUAT","c":39.100,"y":"5","s":"100K-300K","i":"📡"},
    {"n":"Geospatial Engineering","u":"UNIVERSITY OF NAIROBI","c":38.200,"y":"4","s":"80K-200K","i":"🗺️"},
    {"n":"Surveying & Geoinformatics","u":"JKUAT","c":35.500,"y":"5","s":"70K-200K","i":"📍"},
    {"n":"Quantity Surveying","u":"UNIVERSITY OF NAIROBI","c":41.200,"y":"4","s":"80K-250K","i":"📐"},
    {"n":"Quantity Surveying","u":"JKUAT","c":38.900,"y":"4","s":"80K-250K","i":"📐"},
    {"n":"Architecture","u":"JKUAT","c":42.100,"y":"6","s":"100K-350K","i":"🏛️"},
    {"n":"Construction Management","u":"JKUAT","c":36.400,"y":"4","s":"70K-200K","i":"👷"},
    {"n":"Agricultural Engineering","u":"JKUAT","c":36.200,"y":"5","s":"60K-180K","i":"🚜"},
    {"n":"Food Science & Technology","u":"JKUAT","c":37.500,"y":"4","s":"60K-150K","i":"🍎"},
    {"n":"Mining Engineering","u":"JKUAT","c":36.800,"y":"5","s":"100K-300K","i":"⛏️"},

    # 3. BUSINESS & ECONOMICS
    {"n":"Accounting","u":"UNIVERSITY OF NAIROBI","c":38.400,"y":"4","s":"60K-250K","i":"📊"},
    {"n":"Accounting","u":"KENYATTA UNIVERSITY","c":35.200,"y":"4","s":"60K-250K","i":"📊"},
    {"n":"Accounting","u":"STRATHMORE UNIVERSITY","c":39.500,"y":"4","s":"80K-300K","i":"📊"},
    {"n":"Finance","u":"UNIVERSITY OF NAIROBI","c":36.500,"y":"4","s":"70K-250K","i":"💰"},
    {"n":"Banking & Finance","u":"KENYATTA UNIVERSITY","c":30.500,"y":"4","s":"50K-180K","i":"🏦"},
    {"n":"Marketing","u":"UNIVERSITY OF NAIROBI","c":34.100,"y":"4","s":"50K-150K","i":"📈"},
    {"n":"Marketing","u":"MOI UNIVERSITY","c":28.400,"y":"4","s":"50K-150K","i":"📈"},
    {"n":"Human Resource Management","u":"KENYATTA UNIVERSITY","c":29.500,"y":"4","s":"50K-150K","i":"👥"},
    {"n":"Supply Chain Management","u":"JKUAT","c":31.200,"y":"4","s":"60K-180K","i":"🚚"},
    {"n":"Entrepreneurship","u":"KISII UNIVERSITY","c":22.500,"y":"4","s":"40K-120K","i":"💡"},
    {"n":"Business Information Technology","u":"STRATHMORE UNIVERSITY","c":36.100,"y":"4","s":"70K-200K","i":"💻"},
    {"n":"Insurance","u":"KENYATTA UNIVERSITY","c":25.800,"y":"4","s":"40K-120K","i":"🛡️"},
    {"n":"Cooperative Management","u":"KARATINA UNIVERSITY","c":24.100,"y":"4","s":"40K-100K","i":"🤝"},

    # 4. LAW, ARTS & HUMANITIES
    {"n":"Bachelor of Laws (LLB)","u":"CATHOLIC UNIVERSITY OF EASTERN AFRICA","c":39.800,"y":"4","s":"80K-300K","i":"⚖️"},
    {"n":"Bachelor of Laws (LLB)","u":"STRATHMORE UNIVERSITY","c":41.500,"y":"4","s":"100K-400K","i":"⚖️"},
    {"n":"Journalism & Mass Communication","u":"UNIVERSITY OF NAIROBI","c":37.200,"y":"4","s":"50K-180K","i":"📰"},
    {"n":"Journalism & Mass Communication","u":"KENYATTA UNIVERSITY","c":34.800,"y":"4","s":"50K-150K","i":"📰"},
    {"n":"Psychology","u":"UNIVERSITY OF NAIROBI","c":38.500,"y":"4","s":"50K-200K","i":"🧠"},
    {"n":"Psychology","u":"KENYATTA UNIVERSITY","c":33.200,"y":"4","s":"50K-180K","i":"🧠"},
    {"n":"Sociology","u":"UNIVERSITY OF NAIROBI","c":32.100,"y":"4","s":"40K-120K","i":"🌍"},
    {"n":"Political Science","u":"UNIVERSITY OF NAIROBI","c":34.600,"y":"4","s":"50K-150K","i":"🏛️"},
    {"n":"International Relations","u":"UNIVERSITY OF NAIROBI","c":37.400,"y":"4","s":"60K-200K","i":"🌐"},
    {"n":"Public Administration","u":"KENYATTA UNIVERSITY","c":31.500,"y":"4","s":"40K-120K","i":"🏢"},
    {"n":"Social Work","u":"UNIVERSITY OF NAIROBI","c":28.200,"y":"4","s":"35K-100K","i":"❤️"},
    {"n":"Community Development","u":"MASENO UNIVERSITY","c":25.600,"y":"4","s":"30K-90K","i":"🏘️"},
    {"n":"Anthropology","u":"UNIVERSITY OF NAIROBI","c":29.500,"y":"4","s":"40K-120K","i":"🗿"},
    {"n":"Philosophy","u":"UNIVERSITY OF NAIROBI","c":30.200,"y":"4","s":"40K-120K","i":"📚"},
    {"n":"Literature","u":"KENYATTA UNIVERSITY","c":27.400,"y":"4","s":"35K-100K","i":"✍️"},
    {"n":"Linguistics","u":"UNIVERSITY OF NAIROBI","c":29.800,"y":"4","s":"40K-100K","i":"🗣️"},
    {"n":"Fine Art","u":"KENYATTA UNIVERSITY","c":25.100,"y":"4","s":"30K-80K","i":"🎨"},
    {"n":"Music","u":"KENYATTA UNIVERSITY","c":24.500,"y":"4","s":"30K-100K","i":"🎵"},
    {"n":"Theatre & Film","u":"KENYATTA UNIVERSITY","c":27.800,"y":"4","s":"40K-150K","i":"🎬"},

    # 5. EDUCATION
    {"n":"Education (Science)","u":"MASENO UNIVERSITY","c":32.500,"y":"4","s":"35K-120K","i":"📚"},
    {"n":"Education (Science)","u":"MOI UNIVERSITY","c":34.200,"y":"4","s":"35K-120K","i":"📚"},
    {"n":"Education (Arts)","u":"MOI UNIVERSITY","c":28.400,"y":"4","s":"30K-100K","i":"📖"},
    {"n":"Education (Arts)","u":"MASENO UNIVERSITY","c":27.200,"y":"4","s":"30K-100K","i":"📖"},
    {"n":"Early Childhood Education","u":"KENYATTA UNIVERSITY","c":26.100,"y":"4","s":"25K-80K","i":"🧸"},
    {"n":"Special Needs Education","u":"KENYATTA UNIVERSITY","c":25.500,"y":"4","s":"30K-90K","i":"🤝"},
    {"n":"Physical Education","u":"KENYATTA UNIVERSITY","c":24.800,"y":"4","s":"30K-80K","i":"🏃"},
    {"n":"Educational Psychology","u":"KENYATTA UNIVERSITY","c":29.400,"y":"4","s":"40K-100K","i":"🧠"},

    # 6. AGRICULTURE & ENVIRONMENT
    {"n":"Agriculture","u":"UNIVERSITY OF NAIROBI","c":29.500,"y":"4","s":"35K-150K","i":"🌾"},
    {"n":"Agriculture","u":"MOI UNIVERSITY","c":24.100,"y":"4","s":"30K-120K","i":"🌾"},
    {"n":"Agribusiness Management","u":"KISII UNIVERSITY","c":22.400,"y":"4","s":"30K-100K","i":"🚜"},
    {"n":"Agricultural Economics","u":"EGERTON UNIVERSITY","c":26.500,"y":"4","s":"40K-120K","i":"📈"},
    {"n":"Animal Science","u":"EGERTON UNIVERSITY","c":23.200,"y":"4","s":"30K-100K","i":"🐄"},
    {"n":"Food Science & Nutrition","u":"KISII UNIVERSITY","c":28.800,"y":"4","s":"40K-120K","i":"🍎"},
    {"n":"Horticulture","u":"JKUAT","c":27.100,"y":"4","s":"30K-100K","i":"🌻"},
    {"n":"Soil Science","u":"UNIVERSITY OF NAIROBI","c":25.500,"y":"4","s":"35K-100K","i":"🪱"},
    {"n":"Environmental Science","u":"KENYATTA UNIVERSITY","c":32.100,"y":"4","s":"40K-150K","i":"🌍"},
    {"n":"Environmental Science","u":"UNIVERSITY OF NAIROBI","c":34.500,"y":"4","s":"45K-150K","i":"🌍"},
    {"n":"Forestry","u":"MOI UNIVERSITY","c":21.500,"y":"4","s":"30K-90K","i":"🌲"},
    {"n":"Wildlife Management","u":"MOI UNIVERSITY","c":24.200,"y":"4","s":"35K-100K","i":"🦁"},
    {"n":"Fisheries & Aquaculture","u":"MOI UNIVERSITY","c":23.100,"y":"4","s":"30K-90K","i":"🐟"},

    # 7. PURE SCIENCES & MATH
    {"n":"Mathematics","u":"UNIVERSITY OF NAIROBI","c":38.500,"y":"4","s":"50K-200K","i":"📐"},
    {"n":"Mathematics","u":"KENYATTA UNIVERSITY","c":32.400,"y":"4","s":"40K-150K","i":"📐"},
    {"n":"Physics","u":"UNIVERSITY OF NAIROBI","c":36.500,"y":"4","s":"50K-200K","i":"⚛️"},
    {"n":"Chemistry","u":"UNIVERSITY OF NAIROBI","c":35.800,"y":"4","s":"45K-180K","i":"🧪"},
    {"n":"Biology","u":"UNIVERSITY OF NAIROBI","c":34.100,"y":"4","s":"40K-150K","i":"🧬"},
    {"n":"Biochemistry","u":"UNIVERSITY OF NAIROBI","c":39.500,"y":"4","s":"60K-200K","i":"🧬"},
    {"n":"Biochemistry","u":"KENYATTA UNIVERSITY","c":37.100,"y":"4","s":"50K-180K","i":"🧬"},
    {"n":"Microbiology","u":"UNIVERSITY OF NAIROBI","c":37.800,"y":"4","s":"50K-180K","i":"🦠"},
    {"n":"Biotechnology","u":"JKUAT","c":38.200,"y":"4","s":"60K-200K","i":"🔬"},
    {"n":"Geology","u":"UNIVERSITY OF NAIROBI","c":33.500,"y":"4","s":"50K-200K","i":"🪨"},
    {"n":"Meteorology","u":"UNIVERSITY OF NAIROBI","c":31.400,"y":"4","s":"40K-150K","i":"🌦️"},

    # 8. COMPUTING & IT
    {"n":"Computer Science","u":"STRATHMORE UNIVERSITY","c":42.500,"y":"4","s":"100K-500K","i":"💻"},
    {"n":"Computer Science","u":"KABARAK UNIVERSITY","c":36.200,"y":"4","s":"60K-300K","i":"💻"},
    {"n":"Information Systems","u":"UNIVERSITY OF NAIROBI","c":40.500,"y":"4","s":"70K-300K","i":"🖥️"},
    {"n":"Information Systems","u":"KENYATTA UNIVERSITY","c":36.100,"y":"4","s":"60K-250K","i":"🖥️"},
    {"n":"Cybersecurity","u":"JKUAT","c":41.200,"y":"4","s":"80K-350K","i":"🛡️"},
    {"n":"Data Science","u":"UNIVERSITY OF NAIROBI","c":43.500,"y":"4","s":"100K-400K","i":"📊"},
    {"n":"Artificial Intelligence","u":"JKUAT","c":43.800,"y":"4","s":"100K-500K","i":"🤖"},
    {"n":"Computer Technology","u":"TECHNICAL UNIVERSITY OF KENYA","c":34.100,"y":"4","s":"50K-200K","i":"🖥️"},
    {"n":"Information Technology","u":"MULTIMEDIA UNIVERSITY","c":33.500,"y":"4","s":"50K-200K","i":"🌐"},
    {"n":"Information Technology","u":"KARATINA UNIVERSITY","c":28.100,"y":"4","s":"40K-150K","i":"🌐"},

    # 9. HOSPITALITY & TOURISM
    {"n":"Hospitality Management","u":"KENYATTA UNIVERSITY","c":29.800,"y":"4","s":"40K-150K","i":"🏨"},
    {"n":"Hospitality Management","u":"MOI UNIVERSITY","c":25.500,"y":"4","s":"35K-120K","i":"🏨"},
    {"n":"Tourism Management","u":"MOI UNIVERSITY","c":26.200,"y":"4","s":"35K-120K","i":"✈️"},
    {"n":"Tourism Management","u":"KENYATTA UNIVERSITY","c":28.500,"y":"4","s":"40K-130K","i":"✈️"},
    {"n":"Travel & Tour Operations","u":"TECHNICAL UNIVERSITY OF KENYA","c":22.100,"y":"4","s":"30K-100K","i":"🧳"},

    # 10. MEDIA & DESIGN
    {"n":"Graphic Design","u":"TECHNICAL UNIVERSITY OF KENYA","c":30.400,"y":"4","s":"40K-150K","i":"🎨"},
    {"n":"Animation & Motion Graphics","u":"MULTIMEDIA UNIVERSITY","c":33.200,"y":"4","s":"50K-180K","i":"🎬"},
    {"n":"Fashion Design","u":"TECHNICAL UNIVERSITY OF KENYA","c":26.100,"y":"4","s":"35K-120K","i":"👗"},
    {"n":"Interior Design","u":"TECHNICAL UNIVERSITY OF KENYA","c":29.500,"y":"4","s":"45K-150K","i":"🛋️"},
    {"n":"Photography","u":"MULTIMEDIA UNIVERSITY","c":28.500,"y":"4","s":"40K-130K","i":"📷"},
    {"n":"Film & Video Production","u":"MULTIMEDIA UNIVERSITY","c":34.100,"y":"4","s":"50K-200K","i":"🎥"},

    # 11. TVET & TECHNICAL (Diplomas/Certificates)
    {"n":"Diploma in Electrical Engineering","u":"KENYA POLYTECHNIC","c":25.500,"y":"3","s":"30K-100K","i":"⚡"},
    {"n":"Diploma in Mechanical Engineering","u":"KENYA POLYTECHNIC","c":24.100,"y":"3","s":"30K-90K","i":"⚙️"},
    {"n":"Diploma in Civil Engineering","u":"KENYA POLYTECHNIC","c":26.200,"y":"3","s":"35K-110K","i":"🏗️"},
    {"n":"Diploma in Information Technology","u":"KENYA POLYTECHNIC","c":23.500,"y":"3","s":"25K-80K","i":"💻"},
    {"n":"Diploma in Business Management","u":"KENYA POLYTECHNIC","c":20.100,"y":"3","s":"25K-70K","i":"💼"},
    {"n":"Diploma in Nursing","u":"KMTC","c":34.500,"y":"3","s":"50K-150K","i":"🩺"},
    {"n":"Diploma in Clinical Medicine","u":"KMTC","c":32.100,"y":"3","s":"45K-130K","i":"🩻"},
    {"n":"Diploma in Pharmacy","u":"KMTC","c":30.800,"y":"3","s":"40K-120K","i":"💊"},
    {"n":"Diploma in Agriculture","u":"BUKURA AGRICULTURAL COLLEGE","c":18.500,"y":"3","s":"25K-70K","i":"🌾"},
    {"n":"Certificate in Plumbing","u":"KENYA POLYTECHNIC","c":15.000,"y":"2","s":"20K-60K","i":"🔧"},
    {"n":"Certificate in Welding","u":"KENYA POLYTECHNIC","c":15.000,"y":"2","s":"20K-60K","i":"⚒️"},
    {"n":"Certificate in Secretarial Studies","u":"KENYA POLYTECHNIC","c":17.500,"y":"2","s":"20K-50K","i":"📝"},
    {"n":"Diploma in Supply Chain Management","u":"KENYA POLYTECHNIC","c":22.100,"y":"3","s":"30K-90K","i":"🚚"},
    {"n":"Diploma in Journalism","u":"KENYA INSTITUTE OF MASS COMMUNICATION","c":27.500,"y":"3","s":"35K-120K","i":"📰"},
        # --- EXPANSION: TVET, DIPLOMAS & CERTIFICATES ---
    
    # 1. KENYA MEDICAL TRAINING COLLEGE (KMTC) - HEALTH
    {"n":"Diploma in Nursing","u":"KMTC NAIROBI","c":34.500,"y":"3","s":"50K-150K","i":"🩺"},
    {"n":"Diploma in Clinical Medicine & Surgery","u":"KMTC NAIROBI","c":32.100,"y":"3","s":"45K-130K","i":"🩻"},
    {"n":"Diploma in Pharmacy","u":"KMTC NAIROBI","c":30.800,"y":"3","s":"40K-120K","i":"💊"},
    {"n":"Diploma in Medical Laboratory Sciences","u":"KMTC NAIROBI","c":29.500,"y":"3","s":"40K-120K","i":"🔬"},
    {"n":"Diploma in Radiography","u":"KMTC NAIROBI","c":31.200,"y":"3","s":"50K-140K","i":"🩻"},
    {"n":"Diploma in Health Records & IT","u":"KMTC NAIROBI","c":24.100,"y":"3","s":"30K-90K","i":"📄"},
    {"n":"Diploma in Nutrition & Dietetics","u":"KMTC NAIROBI","c":26.500,"y":"3","s":"35K-100K","i":"🍎"},
    {"n":"Diploma in Dental Technology","u":"KMTC NAIROBI","c":28.200,"y":"3","s":"40K-110K","i":"🦷"},
    {"n":"Diploma in Orthopaedic Technology","u":"KMTC NAIROBI","c":25.800,"y":"3","s":"35K-100K","i":"🦴"},
    {"n":"Diploma in Occupational Therapy","u":"KMTC NAIROBI","c":27.100,"y":"3","s":"35K-100K","i":"💪"},

    # 2. KENYA POLYTECHNIC / TECHNICAL UNIVERSITY OF KENYA - ENGINEERING
    {"n":"Diploma in Electrical & Electronic Engineering","u":"KENYA POLYTECHNIC","c":28.500,"y":"3","s":"35K-100K","i":"⚡"},
    {"n":"Diploma in Mechanical Engineering","u":"KENYA POLYTECHNIC","c":27.100,"y":"3","s":"35K-100K","i":"⚙️"},
    {"n":"Diploma in Civil Engineering","u":"KENYA POLYTECHNIC","c":29.200,"y":"3","s":"40K-110K","i":"🏗️"},
    {"n":"Diploma in Automotive Engineering","u":"KENYA POLYTECHNIC","c":25.500,"y":"3","s":"35K-100K","i":"🚗"},
    {"n":"Diploma in Building Technology","u":"KENYA POLYTECHNIC","c":26.800,"y":"3","s":"35K-100K","i":"🧱"},
    {"n":"Diploma in Architecture","u":"KENYA POLYTECHNIC","c":30.100,"y":"3","s":"40K-120K","i":"🏛️"},
    {"n":"Diploma in Quantity Surveying","u":"KENYA POLYTECHNIC","c":29.800,"y":"3","s":"40K-120K","i":"📐"},
    {"n":"Diploma in Land Surveying","u":"KENYA POLYTECHNIC","c":27.500,"y":"3","s":"35K-100K","i":"📍"},
    {"n":"Diploma in Refrigeration & Air Conditioning","u":"KENYA POLYTECHNIC","c":23.200,"y":"3","s":"30K-90K","i":"❄️"},
    {"n":"Diploma in Telecommunications","u":"KENYA POLYTECHNIC","c":28.100,"y":"3","s":"35K-110K","i":"📡"},

    # 3. KENYA POLYTECHNIC - IT & BUSINESS
    {"n":"Diploma in Information Communication Technology","u":"KENYA POLYTECHNIC","c":30.500,"y":"3","s":"35K-120K","i":"💻"},
    {"n":"Diploma in Computer Science","u":"KENYA POLYTECHNIC","c":32.100,"y":"3","s":"40K-130K","i":"🖥️"},
    {"n":"Diploma in Business Management","u":"KENYA POLYTECHNIC","c":25.800,"y":"3","s":"30K-90K","i":"💼"},
    {"n":"Diploma in Sales & Marketing","u":"KENYA POLYTECHNIC","c":23.500,"y":"3","s":"30K-80K","i":"📈"},
    {"n":"Diploma in Human Resource Management","u":"KENYA POLYTECHNIC","c":24.100,"y":"3","s":"30K-80K","i":"👥"},
    {"n":"Diploma in Supply Chain Management","u":"KENYA POLYTECHNIC","c":26.200,"y":"3","s":"30K-90K","i":"🚚"},
    {"n":"Diploma in Accountancy","u":"KENYA POLYTECHNIC","c":28.400,"y":"3","s":"35K-100K","i":"📊"},
    {"n":"Diploma in Secretarial Studies","u":"KENYA POLYTECHNIC","c":22.500,"y":"3","s":"25K-70K","i":"📝"},
    {"n":"Diploma in Library & Information Science","u":"KENYA POLYTECHNIC","c":21.800,"y":"3","s":"25K-70K","i":"📚"},

    # 4. KENYA INSTITUTE OF MASS COMMUNICATION (KIMC)
    {"n":"Diploma in Broadcast Journalism","u":"KIMC NAIROBI","c":33.500,"y":"3","s":"50K-150K","i":"📺"},
    {"n":"Diploma in Print Journalism","u":"KIMC NAIROBI","c":31.200,"y":"3","s":"45K-130K","i":"📰"},
    {"n":"Diploma in Film & Video Production","u":"KIMC NAIROBI","c":34.100,"y":"3","s":"60K-180K","i":"🎥"},
    {"n":"Diploma in Public Relations","u":"KIMC NAIROBI","c":32.800,"y":"3","s":"50K-140K","i":"🤝"},
    {"n":"Diploma in Advertising","u":"KIMC NAIROBI","c":30.500,"y":"3","s":"45K-130K","i":"📢"},
    {"n":"Diploma in Sound Engineering","u":"KIMC NAIROBI","c":29.100,"y":"3","s":"50K-150K","i":"🎧"},
    {"n":"Diploma in Photography","u":"KIMC NAIROBI","c":27.500,"y":"3","s":"40K-120K","i":"📷"},

    # 5. KENYA UTALII COLLEGE - HOSPITALITY & TOURISM
    {"n":"Diploma in Food & Beverage Management","u":"KENYA UTALII COLLEGE","c":30.100,"y":"3","s":"50K-150K","i":"🍽️"},
    {"n":"Diploma in Hotel Management","u":"KENYA UTALII COLLEGE","c":32.500,"y":"3","s":"60K-180K","i":"🏨"},
    {"n":"Diploma in Tourism Management","u":"KENYA UTALII COLLEGE","c":29.800,"y":"3","s":"45K-140K","i":"✈️"},
    {"n":"Diploma in Tour Guiding & Administration","u":"KENYA UTALII COLLEGE","c":26.500,"y":"3","s":"40K-120K","i":"🗺️"},
    {"n":"Diploma in Baking & Pastry","u":"KENYA UTALII COLLEGE","c":24.100,"y":"3","s":"35K-110K","i":"🧁"},
    {"n":"Diploma in Housekeeping & Laundry","u":"KENYA UTALII COLLEGE","c":21.500,"y":"3","s":"30K-90K","i":"🧹"},

    # 6. BUKURA AGRICULTURAL COLLEGE
    {"n":"Diploma in General Agriculture","u":"BUKURA AGRICULTURAL COLLEGE","c":24.500,"y":"3","s":"30K-90K","i":"🌾"},
    {"n":"Diploma in Agribusiness Management","u":"BUKURA AGRICULTURAL COLLEGE","c":23.100,"y":"3","s":"30K-80K","i":"🚜"},
    {"n":"Diploma in Horticulture","u":"BUKURA AGRICULTURAL COLLEGE","c":22.800,"y":"3","s":"25K-80K","i":"🌻"},
    {"n":"Diploma in Animal Health & Production","u":"BUKURA AGRICULTURAL COLLEGE","c":25.200,"y":"3","s":"30K-90K","i":"🐄"},
    {"n":"Diploma in Agricultural Engineering","u":"BUKURA AGRICULTURAL COLLEGE","c":26.100,"y":"3","s":"35K-100K","i":"⚙️"},

    # 7. RIFT VALLEY TECHNICAL TRAINING INSTITUTE (RVTTI)
    {"n":"Diploma in Mechanical Engineering (Production)","u":"RVTTI ELDORET","c":24.100,"y":"3","s":"30K-90K","i":"⚙️"},
    {"n":"Diploma in Electrical & Electronics","u":"RVTTI ELDORET","c":25.500,"y":"3","s":"35K-100K","i":"⚡"},
    {"n":"Diploma in Automotive Engineering","u":"RVTTI ELDORET","c":22.800,"y":"3","s":"30K-90K","i":"🚗"},
    {"n":"Diploma in Building Technology","u":"RVTTI ELDORET","c":23.200,"y":"3","s":"30K-90K","i":"🧱"},
    {"n":"Diploma in Applied Biology","u":"RVTTI ELDORET","c":26.500,"y":"3","s":"35K-100K","i":"🧬"},
    {"n":"Diploma in Analytical Chemistry","u":"RVTTI ELDORET","c":27.100,"y":"3","s":"35K-100K","i":"🧪"},
    {"n":"Diploma in Fashion Design & Clothing Tech","u":"RVTTI ELDORET","c":21.000,"y":"3","s":"25K-80K","i":"👗"},

    # 8. MERU NATIONAL POLYTECHNIC & OTHERS
    {"n":"Diploma in ICT","u":"MERU NATIONAL POLYTECHNIC","c":26.500,"y":"3","s":"30K-90K","i":"💻"},
    {"n":"Diploma in Business Administration","u":"MERU NATIONAL POLYTECHNIC","c":22.100,"y":"3","s":"25K-80K","i":"💼"},
    {"n":"Diploma in Agriculture","u":"MERU NATIONAL POLYTECHNIC","c":21.500,"y":"3","s":"25K-80K","i":"🌾"},
    {"n":"Diploma in Civil Engineering","u":"MERU NATIONAL POLYTECHNIC","c":24.800,"y":"3","s":"30K-90K","i":"🏗️"},
    
    {"n":"Diploma in Marine Engineering","u":"BANDARI COLLEGE MOMBASA","c":28.100,"y":"3","s":"50K-150K","i":"🚢"},
    {"n":"Diploma in Shipping & Logistics","u":"BANDARI COLLEGE MOMBASA","c":25.500,"y":"3","s":"40K-120K","i":"⚓"},
    {"n":"Diploma in Mechanical Engineering (Marine)","u":"BANDARI COLLEGE MOMBASA","c":26.800,"y":"3","s":"45K-130K","i":"⚙️"},

    {"n":"Diploma in Petroleum Geoscience","u":"KIGANJO PETROLEUM INSTITUTE","c":29.100,"y":"3","s":"60K-180K","i":"🛢️"},
    {"n":"Diploma in Petroleum Engineering","u":"KIGANJO PETROLEUM INSTITUTE","c":30.500,"y":"3","s":"70K-200K","i":"🛢️"},

    # 9. CERTIFICATES & ARTISAN COURSES (For D and E grades)
    {"n":"Certificate in Plumbing","u":"KENYA POLYTECHNIC","c":16.000,"y":"2","s":"20K-60K","i":"🔧"},
    {"n":"Certificate in Welding & Fabrication","u":"KENYA POLYTECHNIC","c":15.500,"y":"2","s":"20K-60K","i":"⚒️"},
    {"n":"Certificate in Masonry","u":"RVTTI ELDORET","c":15.000,"y":"2","s":"20K-50K","i":"🧱"},
    {"n":"Certificate in Motor Vehicle Mechanics","u":"RVTTI ELDORET","c":16.200,"y":"2","s":"25K-60K","i":"🚗"},
    {"n":"Certificate in Electrical Installation","u":"MERU NATIONAL POLYTECHNIC","c":17.100,"y":"2","s":"20K-60K","i":"⚡"},
    {"n":"Artisan in Carpentry & Joinery","u":"KENYA POLYTECHNIC","c":12.000,"y":"2","s":"15K-40K","i":"🪵"},
    {"n":"Artisan in Bricklaying","u":"KENYA POLYTECHNIC","c":12.000,"y":"2","s":"15K-40K","i":"🧱"},
    {"n":"Artisan in Tailoring & Dressmaking","u":"RVTTI ELDORET","c":13.500,"y":"2","s":"15K-45K","i":"✂️"}
]
]

SCHOLARSHIPS = [
{"name":"Equity Bank Wings to Fly","amount":"Full tuition + stipend","major":"Any","min_gpa":3.0,"income_req":"Low income","deadline":"March 31","link":"https://equitygroupfoundation.com"},
{"name":"Kenya Government (HELB) Undergraduate","amount":"Up to KES 60,000/yr","major":"Any","min_gpa":2.5,"income_req":"Any","deadline":"Rolling","link":"https://helb.co.ke"},
{"name":"Mastercard Foundation Scholars Program","amount":"Full scholarship","major":"STEM, Agriculture, Education","min_gpa":3.2,"income_req":"Low income","deadline":"Dec 15","link":"https://mastercardfdn.org"},
{"name":"DAAD Kenya","amount":"KES 150K–300K","major":"Engineering, CS, Agriculture","min_gpa":3.0,"income_req":"Any","deadline":"May 30","link":"https://daad-kenya.org"},
{"name":"KCB Foundation 2jiajiri","amount":"KES 100,000","major":"Technical","min_gpa":2.0,"income_req":"Youth 18-35","deadline":"Ongoing","link":"https://kcbgroup.com"},
{"name":"Zawadi Africa","amount":"KES 200,000/yr","major":"STEM, Business","min_gpa":3.5,"income_req":"Low income girls","deadline":"Feb 28","link":"https://zawadiafrica.org"},
]

CHATBOT_QA = [
{"keywords":["calculate cluster points","how cluster points","cluster points formula","weighted cluster"],"answer":"Cluster points = (sum of your best 7 subject points / 84) × 48. Grade points: A=12, A-=11, B+=10, B=9, B-=8, C+=7, C=6, C-=5, D+=4, D=3, D-=2, E=1."},
{"keywords":["nursing b-","can i do nursing","nursing requirements"],"answer":"Minimum cluster points for Nursing: UoN 43.676, Maseno 42.529, Moi 42.390, Egerton 42.166, Kisii 42.080. A B- (8 points) can qualify if your overall cluster meets the cutoff."},
{"keywords":["computer science cutoff","cs cutoff","computer science points"],"answer":"Computer Science cutoffs: UoN 44.825, JKUAT 44.101, Kenyatta 43.497, Multimedia 41.039, Dedan Kimathi 39.746, Maseno 38.155, Masinde Muliro 36.480."},
{"keywords":["best university engineering","engineering university kenya"],"answer":"Top engineering universities: University of Nairobi, JKUAT, Kenyatta University, Moi University. UoN and JKUAT have the highest cutoffs."},
{"keywords":["revise kuccps application","change kuccps","edit kuccps"],"answer":"Yes, during the revision period (usually 2-3 weeks after results). You can log into the KUCCPS student portal and change your course/university choices. The exact dates are announced on the KUCCPS website."},
{"keywords":["missed kuccps deadline","late application"],"answer":"If you miss the deadline, you may not be placed. However, KUCCPS sometimes opens a second revision window or you can apply for inter-institution transfer later. Contact KUCCPS directly for appeals."},
{"keywords":["marketable courses kenya","best courses for jobs"],"answer":"Highly marketable courses: Medicine, Computer Science, Software Engineering, Nursing, Actuarial Science, Civil/Electrical/Mechanical Engineering, Pharmacy, and IT."},
{"keywords":["transfer university kuccps","inter-institution transfer"],"answer":"Yes, inter-institution transfer is possible. You must apply through your current university's registrar after one academic year, subject to vacancies and meeting the target university's requirements."},
{"keywords":["medicine requirements","mbchb requirements","medicine subjects"],"answer":"Medicine (MBChB) requires strong grades in Biology, Chemistry, and either Physics or Mathematics. Minimum cutoffs: UoN 45.584, Kenyatta 45.433, Moi 45.087, JKUAT 45.048."},
{"keywords":["law subjects","requirements for law","llb requirements"],"answer":"Law (LLB) requires English (minimum B), and any other two subjects from Group 2 or 3. Cutoffs: UoN 42.500, Kenyatta 42.000."},
{"keywords":["c+ join university","c+ mean grade"],"answer":"A mean grade of C+ is the minimum for university admission in Kenya. Competitive courses require much higher cluster points."},
{"keywords":["tvet courses kuccps","diploma through kuccps"],"answer":"Yes, KUCCPS places students into TVET institutes for diploma and certificate courses."},
{"keywords":["helb after kuccps","apply for helb","helb requirements"],"answer":"After KUCCPS placement, apply for HELB online. You need your admission letter, national ID, and parents' details."},
{"keywords":["software engineering universities","software engineering kenya"],"answer":"Software Engineering is offered at Multimedia University (cutoff 41.368), JKUAT, and some private universities."},
{"keywords":["difference between computer science and it","cs vs it"],"answer":"Computer Science focuses on theory, algorithms, programming, and software development. IT focuses on networks, databases, system administration, and user support."},
{"keywords":["highest employment courses","courses with jobs"],"answer":"Medicine, Pharmacy, Nursing, Computer Science, Civil Engineering, and Education (Science) have consistently high employment rates in Kenya."},
{"keywords":["study abroad after kuccps","study overseas"],"answer":"Yes, after completing first year, you can apply for transfer to a foreign university. Credits may be transferred."},
{"keywords":["inter institution transfer","how to transfer university"],"answer":"Steps: 1) Complete at least one academic year. 2) Get a release letter from your current university. 3) Apply to the target university. 4) KUCCPS approval."},
{"keywords":["b plain courses","courses for b plain"],"answer":"With B plain, you can aim for: Education (Science/Arts), Bachelor of Commerce, Actuarial Science (JKUAT/Kenyatta), IT, and some diploma programmes."},
{"keywords":["pilot training kenya","pilot requirements"],"answer":"Pilot training is not under KUCCPS. You need to apply directly to aviation schools."},
{"keywords":["admission chances","will i get admitted","chances of placement"],"answer":"Use the calculator. Enter your 7 subjects and grades and click Calculate My Cluster Points. The tool will show qualified, close, and not-qualified courses."},
{"keywords":["private universities kuccps","private university list"],"answer":"KUCCPS places students into some private universities. Government sponsorship rules vary, so check the current KUCCPS placement information."},
{"keywords":["education minimum grade","teaching courses requirements"],"answer":"Education (Arts) cutoffs: Kenyatta 33.556, UoN 32.421, Egerton 32.306. Education (Science) cutoffs: Kenyatta 37.208, UoN 36.127."},
{"keywords":["change course after admission","change course kuccps"],"answer":"You can apply for course change through your university's registrar, usually after first semester."},
{"keywords":["easiest engineering","lowest engineering cutoff"],"answer":"Among the listed engineering courses, Marine Engineering (JKUAT 35.669) and Mechanical Engineering (UoN 41.835, JKUAT 41.450) have relatively lower cutoffs."},
{"keywords":["download admission letter","kuccps admission letter"],"answer":"After KUCCPS placement, log into the KUCCPS student portal and use the admission-letter option shown in your account."},
{"keywords":["weighted cluster subjects","subject weighting"],"answer":"Some courses weight certain subjects more. The system uses your best 7 subjects for the simplified calculator, but actual course requirements can require specific subjects."},
{"keywords":["courses no mathematics","without maths"],"answer":"Courses that don't require Math may include Law, Journalism, Communication, Music, Art, History, Social Work, and many arts/humanities."},
{"keywords":["best technology courses kenya","tech courses"],"answer":"Top technology courses: Computer Science, Software Engineering, Information Technology, Cybersecurity, Data Science, and Artificial Intelligence."},
{"keywords":["courses for coding","love coding"],"answer":"If you love coding, choose Software Engineering, Computer Science, or IT. These focus on programming and system design."},
{"keywords":["jkuat vs ku computer science","compare jkuat and ku"],"answer":"JKUAT CS cutoff 44.101, KU CS 43.497 in this dataset. Both are strong options."},
{"keywords":["lowest cutoff universities","easy to get in"],"answer":"Some lower-cutoff options include Masinde Muliro CS 36.48, Maseno IT 31.702, and JKUAT Marine Engineering 35.669."},
{"keywords":["architecture requirements","architecture cutoff"],"answer":"Architecture cutoff in this dataset is UoN 42.990. Check current subject requirements before applying."},
{"keywords":["mechatronics careers","mechatronics jobs"],"answer":"Mechatronics Engineering can lead to robotics, automation, automotive, manufacturing, controls and R&D careers."},
{"keywords":["fully government sponsored","government sponsorship"],"answer":"Government sponsorship depends on the current funding and placement rules. Check current KUCCPS/HELB information."},
]

# Add this at the bottom of your data.py file (replace the old CHATBOT_QA)

CAREER_QA = [
    # Category 1: Career Discovery
    {"keywords": ["career guidance", "what is career guidance", "choose right career", "career choice"], "answer": "Career guidance is the process of helping individuals understand their interests, abilities, values, and qualifications so they can choose suitable career paths and make informed professional decisions. Start by identifying subjects you enjoy and comparing them with available occupations."},
    {"keywords": ["discover talents", "personality career", "passion vs career", "strongest subjects", "career pays well", "don't know career"], "answer": "To discover your path, examine activities you learn quickly and problems you solve effectively. Income is important, but you should also consider your abilities, interests, and long-term satisfaction. If you don't know what career you want, explore different career families and complete a career assessment."},
    
    # Category 2: Tech & Engineering Careers
    {"keywords": ["software engineer", "software engineering", "developer"], "answer": "A software engineer designs, develops, tests, and maintains software applications and computer systems. They may work on websites, mobile applications, enterprise systems, and other digital products. Key subjects: Mathematics, Physics, Computer Studies."},
    {"keywords": ["data scientist", "data science"], "answer": "A data scientist analyses large datasets, identifies patterns, builds predictive models, and communicates findings that help organizations make decisions. Key subjects: Mathematics, Statistics, Computer Science."},
    {"keywords": ["cybersecurity", "cyber security"], "answer": "A cybersecurity specialist protects computer networks, systems, and information against cyberattacks, unauthorized access, and security vulnerabilities."},
    {"keywords": ["civil engineer", "civil engineering"], "answer": "A civil engineer plans, designs, supervises, and maintains infrastructure such as roads, bridges, buildings, drainage systems, and water infrastructure. Requires strong Mathematics and Physics."},
    {"keywords": ["mechanical engineer", "mechanical engineering"], "answer": "A mechanical engineer designs, develops, tests, and maintains mechanical systems, machinery, engines, and industrial equipment."},
    {"keywords": ["electrical engineer", "electrical engineering"], "answer": "An electrical engineer designs and works with electrical systems, power generation, transmission, control systems, and electrical equipment."},
    {"keywords": ["ai engineer", "artificial intelligence", "machine learning"], "answer": "AI engineering involves designing, developing, integrating, and maintaining systems that use artificial intelligence to perform tasks like prediction, language processing, and automation. Machine learning engineers develop models that learn patterns from data."},
    {"keywords": ["cloud engineering", "cloud computing"], "answer": "Cloud engineering involves designing, deploying, and managing computing infrastructure and services hosted on cloud platforms (like AWS, Azure, or Google Cloud)."},
    {"keywords": ["robotics", "mechatronics"], "answer": "Robotics and Mechatronics combine mechanical engineering, electronics, computer programming, and control systems to design and develop automated machines and robots."},

    # Category 3: Medical & Health Careers
    {"keywords": ["medical doctor", "doctor", "medicine", "mbchb"], "answer": "A medical doctor assesses patients, diagnoses illnesses, recommends treatments, and supports disease prevention. The profession requires recognized medical education (MBChB), clinical training, and professional registration."},
    {"keywords": ["nurse", "nursing"], "answer": "Registered nurses provide patient care, support treatment, and promote health. Career pathways include clinical education, research, management, and community health. Requires strong Biology, Chemistry, and English."},
    {"keywords": ["pharmacist", "pharmacy"], "answer": "A pharmacist supports the safe preparation, supply, and appropriate use of medicines. Requires a Bachelor of Pharmacy (BPharm) and professional registration."},
    {"keywords": ["clinical officer", "clinical medicine"], "answer": "Clinical officers follow a separate clinical training pathway (Diploma or Degree) and have their own professional scope and registration requirements for diagnosing and treating patients."},
    {"keywords": ["radiographer", "radiography"], "answer": "A radiographer operates medical imaging equipment (like X-rays and MRIs) and produces diagnostic images, following radiation safety and professional practice requirements."},

    # Category 4: Business & Finance Careers
    {"keywords": ["accountant", "accounting", "cpa"], "answer": "An accountant prepares financial records, analyses transactions, produces financial reports, and supports organizations with financial management and compliance. Certifications like CPA are highly recommended."},
    {"keywords": ["actuarial science", "actuary"], "answer": "Actuarial science applies mathematics, statistics, and financial theory to assess risk, particularly in insurance, pensions, and financial services. Highly math-intensive."},
    {"keywords": ["economist", "economics"], "answer": "An economist studies how resources, markets, businesses, and governments operate. They analyse economic information and advise on economic decisions and policies."},
    {"keywords": ["supply chain", "procurement"], "answer": "Supply chain management involves planning and coordinating the movement of goods, services, information, and resources from suppliers to customers."},
    {"keywords": ["entrepreneur", "entrepreneurship", "business"], "answer": "Entrepreneurship involves identifying business opportunities, developing products or services, managing operations, and building sustainable enterprises."},

    # Category 5: Law, Creative & Social Sciences
    {"keywords": ["lawyer", "law", "llb"], "answer": "A lawyer provides legal advice, interprets legislation, prepares legal documents, and represents clients. Requires an LLB degree and completion of the Kenya School of Law (KSL)."},
    {"keywords": ["graphic designer", "graphic design"], "answer": "A graphic designer creates visual communication materials such as logos, advertisements, digital graphics, publications, and brand identities."},
    {"keywords": ["journalist", "journalism", "media"], "answer": "A journalist researches, verifies, and communicates information through newspapers, websites, television, radio, and other media. Requires strong English and communication skills."},
    {"keywords": ["architect", "architecture"], "answer": "An architect designs buildings and spaces, prepares architectural plans, considers safety and functionality, and coordinates with other construction professionals."},

    # Category 6: KCSE & Subject Matching
    {"keywords": ["b plain", "b plain career"], "answer": "With a B plain, many careers are possible depending on your specific subject grades. You can pursue Education, Business, IT, or certain engineering/actuarial pathways if your Math and Sciences are strong. EduBot evaluates your full results rather than just the overall grade."},
    {"keywords": ["c plain", "c plain career"], "answer": "With a C plain, you can pursue diploma-level professional training, technical occupations, business, ICT, hospitality, creative fields, and other skills-based careers."},
    {"keywords": ["good at mathematics", "math careers", "love math"], "answer": "If you are good at Mathematics, consider Actuarial Science, Statistics, Economics, Accounting, Data Science, Engineering, Computer Science, and Quantitative Research."},
    {"keywords": ["good at biology", "biology careers"], "answer": "If you are good at Biology, consider Medicine, Nursing, Pharmacy, Biomedical Science, Laboratory Technology, Biotechnology, Agriculture, and Environmental Science."},
    {"keywords": ["good at physics", "physics careers"], "answer": "If you are good at Physics, consider Engineering, Physical Sciences, Electronics, Renewable Energy, Astronomy, and Medical Physics."},
    {"keywords": ["good at english", "english careers"], "answer": "If you are good at English, consider Journalism, Communication, Public Relations, Law, Education, Editing, Writing, and Publishing."},
    {"keywords": ["programmer without computer studies", "coding without cs"], "answer": "Yes, you can become a programmer without taking Computer Studies in high school. You can learn through Mathematics, independent learning (bootcamps, online courses), practical projects, and recognized academic programmes. Degree admissions may still require Math."},
    
    # Category 7: Course-to-Career Mapping
    {"keywords": ["computer science career", "careers with computer science", "cs jobs"], "answer": "A degree in Computer Science can lead to careers as a Software Engineer, Systems Developer, Data Scientist, Cybersecurity Specialist, Database Administrator, AI Engineer, or Research Scientist."},
    {"keywords": ["information technology career", "it jobs", "careers with it"], "answer": "IT graduates may pursue Systems Administration, IT Support, Network Administration, Cloud Operations, Database Management, Cybersecurity, and IT Consulting."},
    {"keywords": ["commerce career", "bcom jobs", "bachelor of commerce"], "answer": "Depending on specialization, BCom graduates can become Accountants, Financial Analysts, Auditors, Marketing Specialists, Business Analysts, and Management Professionals."},
]

# Fallback knowledge from previous categories
GENERAL_QA = [
    {"keywords": ["kuccps", "what is kuccps"], "answer": "KUCCPS is the Kenya Universities and Colleges Central Placement Service. It coordinates the placement of eligible students into universities and colleges."},
    {"keywords": ["change university", "transfer", "change course"], "answer": "Course and programme changes may be possible through the official KUCCPS transfer process, subject to the applicable rules, deadlines, and programme requirements."},
    {"keywords": ["helb", "helb funding", "loan"], "answer": "HELB provides financing for government-sponsored students. Funding depends on the applicable student financing framework, eligibility criteria, and application process. Always verify via the official HELB portal."}
]

# Combine them for the engine
CHATBOT_QA = CAREER_QA + GENERAL_QA
