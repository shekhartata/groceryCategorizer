from openai import OpenAI
import os
from dotenv import load_dotenv
from flask import Flask, request, render_template, send_file
import io

# Load environment variables
load_dotenv()

# Set up OpenAI API key
client = OpenAI(api_key="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")

app = Flask(__name__)

def categorize_products(products):
    prompt = """
    You are an expert in product categorization. Categorize each product below into an appropriate category.
    Output format: "Categoy (in bold) followed by a colon, then a list of products in that category, one product per line. Sorted in alphabetical order"

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
                
                return send_file(
                    io.BytesIO(output.getvalue().encode('utf-8')),
                    mimetype='text/plain',
                    as_attachment=True,
                    download_name='output.txt'
                )
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
            .upload-form {
                text-align: center;
                margin-top: 20px;
            }
            .file-input {
                margin: 20px 0;
            }
            .submit-btn {
                background-color: #4CAF50;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
            }
            .submit-btn:hover {
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
        </script>
    </body>
    </html>
    '''

if __name__ == '__main__':
    app.run(debug=True)