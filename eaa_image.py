import os 
os.environ["CUDA_VISIBLE_DEVICES"]="" 
def create_placeholder(text,w=512,h=512): 
    img=Image.new("RGB",(w,h),color=(30,30,60)) 
    d=ImageDraw.Draw(img) 
    d.text((20,20),text,fill=(200,200,255)) 
    img.save("output.png"); return "output.png" 
print(create_placeholder("EAA V8")) 
