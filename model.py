from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import os

client = MongoClient(os.getenv('MONGODB_URI', 'mongodb://localhost:27017/myscheme'))
db = client.get_database()

class User:
    collection = db.users
    
    def __init__(self, name, email, password, aadhar, phone, role='user'):
        self.name = name
        self.email = email
        self.password = password
        self.aadhar = aadhar
        self.phone = phone
        self.role = role
        self.created_at = datetime.utcnow()
    
    def save(self):
        result = self.collection.insert_one(self.__dict__)
        self.id = result.inserted_id
        return self
    
    @classmethod
    def find_by_email(cls, email):
        user_data = cls.collection.find_one({'email': email})
        if user_data:
            user = cls.__new__(cls)
            user.__dict__ = user_data
            return user
        return None
    
    @classmethod
    def find_by_id(cls, user_id):
        user_data = cls.collection.find_one({'_id': ObjectId(user_id)})
        if user_data:
            user = cls.__new__(cls)
            user.__dict__ = user_data
            return user
        return None

class Scheme:
    collection = db.schemes
    
    def __init__(self, name, description, eligibility, benefits, documentsRequired, link=''):
        self.name = name
        self.description = description
        self.eligibility = eligibility
        self.benefits = benefits
        self.documentsRequired = documentsRequired
        self.link = link
        self.created_at = datetime.utcnow()
    
    def save(self):
        result = self.collection.insert_one(self.__dict__)
        self.id = result.inserted_id
        return self
    
    def to_dict(self):
        return {
            'id': str(self.id),
            'name': self.name,
            'description': self.description,
            'eligibility': self.eligibility,
            'benefits': self.benefits,
            'documentsRequired': self.documentsRequired,
            'link': self.link,
            'createdAt': self.created_at.isoformat()
        }
    
    @classmethod
    def find_by_id(cls, scheme_id):
        scheme_data = cls.collection.find_one({'_id': ObjectId(scheme_id)})
        if scheme_data:
            scheme = cls.__new__(cls)
            scheme.__dict__ = scheme_data
            return scheme
        return None
    
    @classmethod
    def get_all(cls):
        return [cls.__new__(cls).__dict__.update(data) or cls.__new__(cls) 
                for data in cls.collection.find()]

class Application:
    collection = db.applications
    
    def __init__(self, user_id, scheme_id, answers, documents, status='pending'):
        self.user_id = user_id
        self.scheme_id = scheme_id
        self.answers = answers
        self.documents = documents
        self.status = status
        self.applied_at = datetime.utcnow()
        self.reviewed_at = None
    
    def save(self):
        result = self.collection.insert_one(self.__dict__)
        self.id = result.inserted_id
        return self
    
    def to_dict(self):
        return {
            'id': str(self.id),
            'userId': self.user_id,
            'schemeId': self.scheme_id,
            'answers': self.answers,
            'documents': self.documents,
            'status': self.status,
            'appliedAt': self.applied_at.isoformat(),
            'reviewedAt': self.reviewed_at.isoformat() if self.reviewed_at else None
        }
    
    @classmethod
    def find_by_id(cls, app_id):
        app_data = cls.collection.find_one({'_id': ObjectId(app_id)})
        if app_data:
            app = cls.__new__(cls)
            app.__dict__ = app_data
            return app
        return None
    
    @classmethod
    def find_by_user(cls, user_id):
        return [cls.__new__(cls).__dict__.update(data) or cls.__new__(cls) 
                for data in cls.collection.find({'user_id': user_id})]
    
    @classmethod
    def get_all(cls):
        return [cls.__new__(cls).__dict__.update(data) or cls.__new__(cls) 
                for data in cls.collection.find()]
