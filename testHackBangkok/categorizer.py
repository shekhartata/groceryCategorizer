from openai import OpenAI
import os
from dotenv import load_dotenv
from flask import Flask, request, render_template, send_file, jsonify
import io
from sentence_transformers import SentenceTransformer
from pymongo import MongoClient
import numpy as np
from datetime import datetime
import threading
from queue import Queue

# Load environment variables
load_dotenv()

# Set up OpenAI API key
client = OpenAI(
api_key=<>
)

# Initialize sentence transformer model
model = SentenceTransformer('all-MiniLM-L6-v2')

# MongoDB connection
mongo_client = MongoClient(
    "mongodb+srv://user-test-sync:shekhartesting@cluster0.eyv8o.mongodb.net/?retryWrites=true&w=majority"
)
db = mongo_client.testing
products_collection = db.documents

# Create vector index if it doesn't exist
try:
    products_collection.create_index([
        ("embedding", "vectorSearch")
    ], {
        "name": "vector_index",
        "numDimensions": 384,  # Dimension for all-MiniLM-L6-v2 model
        "similarity": "cosine"
    })
except Exception as e:
    print(f"Index creation error (might already exist): {str(e)}")

# Create a queue for async processing
processing_queue = Queue()

def async_mongodb_processor():
    while True:
        try:
            # Get data from queue
            data = processing_queue.get()
            if data is None:  # Poison pill to stop the thread
                break
                
            result, products = data
            
            # Process categories and prepare documents for batch insert
            documents = []
            current_category = None
            for line in result.split('\n'):
                if line.startswith('**'):  # Category line
                    current_category = line.strip('*').strip()
                elif line.strip() and current_category:
                    product_name = line.strip()
                    # Create embedding for the product
                    embedding = create_embedding(product_name)
                    # Prepare document for batch insert
                    documents.append({
                        'product_name': product_name,
                        'category': current_category,
                        'embedding': embedding,
                        'created_at': datetime.utcnow()
                    })
            
            # Batch insert all documents at once
            if documents:
                products_collection.insert_many(documents)
                print(f"Successfully inserted {len(documents)} documents")
            
            processing_queue.task_done()
        except Exception as e:
            print(f"Error in async processing: {str(e)}")
            processing_queue.task_done()

# Start the async processor thread
processor_thread = threading.Thread(target=async_mongodb_processor, daemon=True)
processor_thread.start()

app = Flask(__name__)

def create_embedding(text):
    return model.encode(text).tolist()

def categorize_products(products):
    prompt = """
    You are an expert in product categorization. Categorize each product below into an appropriate category.
    Output format: "Categoy (in bold) followed by a colon, then a list of products in that category, one product per line. Sorted in alphabetical order. Also dont add any other text to the output"

    Products:
    """

    for product in products:
        prompt += f"Product: {product}\n\n"

    prompt += "Categories should be broad but specific (e.g., Electronics, Clothing, Home Appliances)."

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": prompt,
            },
        ],
        max_tokens=1500,
        temperature=0.3
    )

    return response.choices[0].message.content.strip()

@app.route('/search', methods=['POST'])
def search_products():
    query = request.json.get('query')
    if not query:
        return jsonify({'error': 'No query provided'}), 400
    
    # Create embedding for the search query
    query_embedding = create_embedding(query)
    
    # Perform vector search in MongoDB
    results = products_collection.aggregate([
        {
            "$vectorSearch": {
                "queryVector": query_embedding,
                "path": "embedding",
                "numCandidates": 100,
                "limit": 5,
                "index": "vector_index_test"
            }
        },
        {
            "$project": {
                "_id": {"$toString": "$_id"},
                "product_name": 1,
                "category": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ])
    
    # Format results for OpenAI context
    context = "Based on the following similar products found:\n\n"
    for result in results:
        context += f"- {result['product_name']} (Category: {result['category']}, Similarity: {(result['score'] * 100):.2f}%)\n"
    
    # Create OpenAI prompt
    prompt = f"""
    Query: {query}
    
    {context}
    
    Please provide a yes or no response about the query, considering the similar products found above. 
    Include relevant information about other products belonging to same category. Avoid mentioning similarity score.
    Also keep the response user-friendly and relevant. If context is empty, please answer - "No items in inventory".
    """
    
    # Get response from OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a product expert who provides detailed information about products and their relationships. Do not provide answers from internet. Just provide the answer based on the products and their relationships."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=500,
            temperature=0.3
        )
        
        ai_response = response.choices[0].message.content.strip()
        
        return jsonify({
            'vector_results': list(results),
            'ai_response': ai_response
        })
    except Exception as e:
        return jsonify({
            'error': f'Error getting AI response: {str(e)}',
            'vector_results': list(results)
        }), 500

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return 'No file part'
        file = request.files['file']
        if file.filename == '':
            return 'No selected file'
        if file and file.filename.endswith('.txt'):
            try:
                # Read the text file
                content = file.read().decode('utf-8')
                
                # Process each line
                products = []
                for line in content.splitlines():
                    product = line.strip()
                    if product:  # Only add non-empty lines
                        products.append(product)
                
                if not products:
                    return "No valid products found in the text file. Please add product names, one per line."
                
                # Categorize products
                result = categorize_products(products)
                
                # Create a text file with results
                output = io.StringIO()
                output.write(result)
                output.seek(0)
                
                # Store the file content for later use
                file_content = output.getvalue()
                
                # Send the file first
                response = send_file(
                    io.BytesIO(file_content.encode('utf-8')),
                    mimetype='text/plain',
                    as_attachment=True,
                    download_name='output.txt'
                )
                
                # Queue the MongoDB processing for async execution
                processing_queue.put((result, products))
                
                return response
            except Exception as e:
                return f'Error processing file: {str(e)}'
        else:
            return 'Please upload a text file (.txt)'
    
    return '''
    <!doctype html>
    <html>
    <head>
        <title>Product Categorizer</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .upload-form, .search-form {
                text-align: center;
                margin-top: 20px;
            }
            .file-input {
                margin: 20px 0;
            }
            .submit-btn, .search-btn {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
            }
            .submit-btn:hover, .search-btn:hover {
                background-color: #45a049;
            }
            .submit-btn:disabled {
                background-color: #cccccc;
                cursor: not-allowed;
            }
            .instructions {
                margin-top: 20px;
                padding: 15px;
                background-color: #e9ecef;
                border-radius: 4px;
                font-size: 14px;
            }
            .loading {
                display: none;
                margin: 20px auto;
                text-align: center;
            }
            .spinner {
                width: 40px;
                height: 40px;
                margin: 0 auto;
                border: 4px solid #f3f3f3;
                border-top: 4px solid #4CAF50;
                border-radius: 50%;
                animation: spin 1s linear infinite;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            .processing-text {
                margin-top: 10px;
                color: #666;
                font-size: 14px;
            }
            .success-message {
                display: none;
                margin-top: 10px;
                color: #4CAF50;
                font-size: 14px;
            }
            .search-results {
                margin-top: 20px;
                text-align: left;
            }
            .search-input {
                padding: 8px;
                width: 300px;
                margin-right: 10px;
                border: 1px solid #ddd;
                border-radius: 4px;
            }
            .result-item {
                padding: 10px;
                border-bottom: 1px solid #eee;
            }
            .result-item:last-child {
                border-bottom: none;
            }
            .score {
                color: #666;
                font-size: 12px;
            }
            .ai-response {
                margin-bottom: 20px;
                padding: 15px;
                background-color: #f8f9fa;
                border-radius: 4px;
                border-left: 4px solid #4CAF50;
            }
            .ai-response h3 {
                margin-top: 0;
                color: #4CAF50;
            }
            .vector-results h3 {
                color: #333;
                margin-bottom: 10px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Product Categorizer</h1>
            <div class="upload-form">
                <form method="post" enctype="multipart/form-data" id="uploadForm">
                    <div class="file-input">
                        <input type="file" name="file" accept=".txt" required id="fileInput">
                    </div>
                    <input type="submit" value="Upload and Categorize" class="submit-btn" id="submitBtn">
                </form>
                <div class="loading" id="loading">
                    <div class="spinner"></div>
                    <div class="processing-text">Processing your file... This may take a few moments.</div>
                </div>
                <div class="success-message" id="successMessage">
                    File processed successfully! You can upload another file.
                </div>
            </div>
            <div class="search-form">
                <input type="text" class="search-input" id="searchInput" placeholder="Search for products...">
                <button class="search-btn" id="searchBtn">Search</button>
                <div class="search-results" id="searchResults"></div>
            </div>
            <div class="instructions">
                <h3>File Format Instructions:</h3>
                <p>Please upload a text file (.txt) with one product name per line:</p>
                <p>Each line should contain a single product name.</p>
                <p>The results will be downloaded as output.txt</p>
            </div>
        </div>

        <script>
            document.getElementById('uploadForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                const submitBtn = document.getElementById('submitBtn');
                const loading = document.getElementById('loading');
                const fileInput = document.getElementById('fileInput');
                const successMessage = document.getElementById('successMessage');
                
                if (fileInput.files.length > 0) {
                    submitBtn.disabled = true;
                    loading.style.display = 'block';
                    successMessage.style.display = 'none';

                    const formData = new FormData(this);
                    
                    try {
                        const response = await fetch('/', {
                            method: 'POST',
                            body: formData
                        });

                        if (response.ok) {
                            // Create a blob from the response
                            const blob = await response.blob();
                            // Create a download link
                            const url = window.URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = 'output.txt';
                            document.body.appendChild(a);
                            a.click();
                            window.URL.revokeObjectURL(url);
                            document.body.removeChild(a);

                            // Reset form and show success message
                            submitBtn.disabled = false;
                            loading.style.display = 'none';
                            fileInput.value = '';
                            successMessage.style.display = 'block';
                        } else {
                            throw new Error('Network response was not ok');
                        }
                    } catch (error) {
                        console.error('Error:', error);
                        submitBtn.disabled = false;
                        loading.style.display = 'none';
                        alert('Error processing file. Please try again.');
                    }
                }
            });

            document.getElementById('searchBtn').addEventListener('click', async function() {
                const searchInput = document.getElementById('searchInput');
                const searchResults = document.getElementById('searchResults');
                const query = searchInput.value.trim();

                if (!query) {
                    alert('Please enter a search query');
                    return;
                }

                try {
                    const response = await fetch('/search', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ query: query })
                    });

                    if (response.ok) {
                        const data = await response.json();
                        searchResults.innerHTML = `
                            <div class="ai-response">
                                <h3>AI Analysis:</h3>
                                <p>${data.ai_response}</p>
                            </div>
                            <div class="vector-results">
                                ${data.vector_results.map(result => `
                                    <div class="result-item">
                                        <div>${result.product_name}</div>
                                        <div>Category: ${result.category}</div>
                                        <div class="score">Similarity Score: ${(result.score * 100).toFixed(2)}%</div>
                                    </div>
                                `).join('')}
                            </div>
                        `;
                    } else {
                        throw new Error('Search failed');
                    }
                } catch (error) {
                    console.error('Error:', error);
                    searchResults.innerHTML = '<div class="result-item">Error performing search. Please try again.</div>';
                }
            });
        </script>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(debug=True)
